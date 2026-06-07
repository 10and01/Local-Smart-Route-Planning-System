# -*- coding: utf-8 -*-
"""
语义匹配模块
使用本地轻量级 Embedding 模型计算关键词与 POI 的语义相似度

模型: sentence-transformers/all-MiniLM-L6-v2 (约 22MB，384维向量)
【修复】针对中文tokenizer产生大量[UNK]的问题，对常见中文关键词使用英文扩展描述
"""

import os
import sys
import pickle
from typing import Dict, List, Optional
from pathlib import Path

import numpy as np

# 屏蔽 tensorflow 避免 numpy 兼容性错误
sys.modules["tensorflow"] = None

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"

# 模型配置
MODEL_NAME = "BAAI/bge-small-zh-v1.5"
EMBEDDING_DIM = 512

# 【项目内模型路径】优先从项目目录加载，不依赖系统缓存
_LOCAL_MODEL_DIR = _PROJECT_ROOT / "data" / "models" / "bge-small-zh-v1.5"

# 【保留兜底】关键词扩展映射（中文模型下基本不需要，保留极少数无意义短词兜底）
_KEYWORD_EN_MAP = {}


def _expand_keyword(keyword: str) -> str:
    """
    【方案A】中文模型原生支持中文，直接返回原词，无需英文映射。
    中文Embedding模型（如BAAI/bge-small-zh-v1.5）对中文短词有良好区分度。
    """
    if not keyword or not isinstance(keyword, str):
        return keyword or ""
    kw = keyword.strip()
    # 兜底：极少数情况如果有映射仍可用
    if kw in _KEYWORD_EN_MAP:
        return _KEYWORD_EN_MAP[kw]
    return kw


class SemanticMatcher:
    """
    语义匹配器：基于本地 Embedding 模型的关键词-POI 语义相似度计算
    """

    _instance: Optional["SemanticMatcher"] = None
    _model = None
    _tokenizer = None
    _poi_embedding_cache: Dict[str, np.ndarray] = {}
    _keyword_embedding_cache: Dict[str, np.ndarray] = {}
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _ensure_initialized(self):
        """延迟初始化模型（优先项目内路径，其次系统缓存）"""
        if self._initialized:
            return
        try:
            import torch
            import torch.nn.functional as F
            from transformers import AutoModel, AutoTokenizer

            # 【项目内加载】优先从项目目录加载模型，完全不依赖网络和系统缓存
            if _LOCAL_MODEL_DIR.exists():
                model_path = str(_LOCAL_MODEL_DIR)
                self._tokenizer = AutoTokenizer.from_pretrained(
                    model_path, local_files_only=True
                )
                self._model = AutoModel.from_pretrained(
                    model_path, local_files_only=True
                )
                self._model.eval()
                self._torch = torch
                self._F = F
                self._initialized = True
                print(f"[SemanticMatcher] 模型加载成功（项目内）: {model_path}")
            else:
                # 回退：尝试系统缓存
                self._tokenizer = AutoTokenizer.from_pretrained(
                    MODEL_NAME, local_files_only=True
                )
                self._model = AutoModel.from_pretrained(
                    MODEL_NAME, local_files_only=True
                )
                self._model.eval()
                self._torch = torch
                self._F = F
                self._initialized = True
                print(f"[SemanticMatcher] 模型加载成功（系统缓存）: {MODEL_NAME}")
        except Exception as e:
            print(f"[SemanticMatcher] 模型加载失败，将回退到规则匹配: {e}")
            self._initialized = False

    def _mean_pooling(self, model_output, attention_mask):
        """Mean Pooling - 取所有 token 嵌入的平均值"""
        token_embeddings = model_output.last_hidden_state
        input_mask_expanded = (
            attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        )
        sum_embeddings = self._torch.sum(token_embeddings * input_mask_expanded, 1)
        sum_mask = self._torch.clamp(input_mask_expanded.sum(1), min=1e-9)
        return sum_embeddings / sum_mask

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        """
        批量编码文本为嵌入向量
        返回: (N, 384) 的归一化向量数组
        """
        self._ensure_initialized()
        if not self._initialized or not texts:
            return np.zeros((len(texts), EMBEDDING_DIM), dtype=np.float32)

        try:
            inputs = self._tokenizer(
                texts,
                padding=True,
                truncation=True,
                return_tensors="pt",
                max_length=128,
            )
            with self._torch.no_grad():
                outputs = self._model(**inputs)
                embeddings = self._mean_pooling(outputs, inputs["attention_mask"])
                embeddings = self._F.normalize(embeddings, p=2, dim=1)
            return embeddings.cpu().numpy().astype(np.float32)
        except Exception as e:
            print(f"[SemanticMatcher] 编码失败: {e}")
            return np.zeros((len(texts), EMBEDDING_DIM), dtype=np.float32)

    def embed_text(self, text: str) -> np.ndarray:
        """编码单条文本"""
        return self.embed_texts([text])[0]

    def get_poi_embedding(self, poi) -> np.ndarray:
        """获取 POI 的嵌入向量（带缓存）"""
        poi_id = getattr(poi, "poi_id", None)
        if poi_id and poi_id in self._poi_embedding_cache:
            return self._poi_embedding_cache[poi_id]

        # 构建 POI 描述文本
        texts = [getattr(poi, "name", "") or ""]
        tags = getattr(poi, "tags", None) or []
        texts.extend(tags)
        category = getattr(poi, "category", None)
        if category:
            texts.append(category)
        sub_category = getattr(poi, "sub_category", None)
        if sub_category:
            texts.append(sub_category)
        desc = "，".join(t for t in texts if t)

        vec = self.embed_text(desc)
        if poi_id:
            self._poi_embedding_cache[poi_id] = vec
        return vec

    def get_keyword_embedding(self, keyword: str) -> np.ndarray:
        """获取关键词的嵌入向量（带内存缓存）"""
        if keyword in self._keyword_embedding_cache:
            return self._keyword_embedding_cache[keyword]
        # 【修复】使用英文扩展描述替代原始中文关键词
        expanded = _expand_keyword(keyword)
        vec = self.embed_text(expanded)
        self._keyword_embedding_cache[keyword] = vec
        return vec

    def compute_similarity(self, text1: str, text2: str) -> float:
        """计算两个文本的语义相似度 (0.0 ~ 1.0)"""
        vec1 = self.get_keyword_embedding(text1)
        vec2 = self.get_keyword_embedding(text2)
        return float(np.dot(vec1, vec2))

    def match_keywords_to_poi(self, keyword_weights: Dict[str, float], poi) -> float:
        """
        计算一组关键词与单个 POI 的加权语义匹配度 (0.0 ~ 1.0)
        【修复】降低归一化放大系数，避免0.6相似度被放大到1.0
        """
        if not keyword_weights:
            return 0.0

        poi_vec = self.get_poi_embedding(poi)
        total_weight = sum(keyword_weights.values())
        weighted_sim = 0.0

        for keyword, weight in keyword_weights.items():
            kw_vec = self.get_keyword_embedding(keyword)
            sim = float(np.dot(kw_vec, poi_vec))
            weighted_sim += weight * sim

        # 【修复】归一化：用总权重的 80% 作为基准分母（原为60%，过度放大）
        return min(1.0, weighted_sim / max(total_weight * 0.8, 0.1))

    def compute_keyword_matches(
        self, keyword_weights: Dict[str, float], poi
    ) -> Dict[str, float]:
        """
        计算每个关键词与 POI 的单独相似度
        返回: {keyword: similarity}
        """
        poi_vec = self.get_poi_embedding(poi)
        result = {}
        for keyword in keyword_weights:
            kw_vec = self.get_keyword_embedding(keyword)
            result[keyword] = float(np.dot(kw_vec, poi_vec))
        return result

    def batch_compute_poi_embeddings(self, pois: List):
        """批量预计算 POI 嵌入（用于城市数据初始化）"""
        descs = []
        for poi in pois:
            texts = [getattr(poi, "name", "") or ""]
            tags = getattr(poi, "tags", None) or []
            texts.extend(tags)
            category = getattr(poi, "category", None)
            if category:
                texts.append(category)
            sub_category = getattr(poi, "sub_category", None)
            if sub_category:
                texts.append(sub_category)
            descs.append("，".join(t for t in texts if t))

        embeddings = self.embed_texts(descs)
        for poi, vec in zip(pois, embeddings):
            poi_id = getattr(poi, "poi_id", None)
            if poi_id:
                self._poi_embedding_cache[poi_id] = vec
        return embeddings

    def clear_cache(self):
        """清空缓存"""
        self._poi_embedding_cache.clear()
        self._keyword_embedding_cache.clear()

    def save_poi_embeddings(self, city: str):
        """保存 POI 嵌入到磁盘"""
        cache_file = _DATA_DIR / f"{city}_poi_embeddings.pkl"
        try:
            with open(cache_file, "wb") as f:
                pickle.dump(self._poi_embedding_cache, f)
            print(f"[SemanticMatcher] POI 嵌入已保存: {cache_file}")
        except Exception as e:
            print(f"[SemanticMatcher] 保存失败: {e}")

    def load_poi_embeddings(self, city: str) -> bool:
        """从磁盘加载 POI 嵌入"""
        cache_file = _DATA_DIR / f"{city}_poi_embeddings.pkl"
        if not cache_file.exists():
            return False
        try:
            with open(cache_file, "rb") as f:
                self._poi_embedding_cache = pickle.load(f)
            print(
                f"[SemanticMatcher] POI 嵌入已加载: {len(self._poi_embedding_cache)} 个"
            )
            return True
        except Exception as e:
            print(f"[SemanticMatcher] 加载失败: {e}")
            return False


# 全局单例
semantic_matcher = SemanticMatcher()
