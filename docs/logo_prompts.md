# 🎨 Logo 生成提示词

> 基于用户提供的参考图风格（罗盘 × 定位标记 × 发光路径 × 神经网络）重新设计的 AI 生图提示词。
>
> 适用工具：Midjourney v6、DALL-E 3、Stable Diffusion XL、Ideogram、FLUX

---

## 方案一：智航罗盘（忠实升级版 · 推荐）

**构图说明**

直接继承参考图的经典构图：外层是一个**粗线条的罗盘圆环**（上下左右四向尖角），内嵌一个饱满的**定位标记（Location Pin）**作为视觉主体。定位标记内部是一条从底部延伸至顶部的**发光曲线路径**，路径上串联着 **3 颗高亮的圆形节点**（代表「三套差异化方案」），节点大小依次递增或均匀分布。背景散布着**稀疏的神经网络连线**（细线 + 小圆点），暗示 LLM 智能大脑。整体采用深蓝到青绿的冷色调，路径使用**青绿 → 琥珀**的渐变发光，形成强烈的视觉焦点。

**核心卖点映射**
- 外层罗盘 → 导航 / 方向 / 出行
- 内层定位标记 → 本地生活 / 地图服务
- 3 颗发光节点 → 深度体验 / 高效省时 / 均衡推荐
- 背景神经网络 → LLM + 经典算法融合

**Midjourney 提示词**
```
A premium 3D logo icon for an AI-powered local route planning app. 
Outer layer: a thick bold compass ring with four sharp directional points (north, south, east, west), deep blue (#003B57) metallic gradient with subtle inner glow. 
Center: a large sleek location pin icon nested inside the compass, filled with dark navy (#0a192f) glassy surface. 
Inside the pin: a glowing winding path line runs from bottom to top, with exactly 3 luminous spherical nodes along the path, gradient from cyan (#00E5FF) at bottom to amber (#FFAB40) at top, soft bloom glow effect. 
Background inside the pin: sparse neural network constellation lines with tiny cyan dots, suggesting AI intelligence. 
Clean white background, smooth 3D rendering, subtle drop shadow under the compass, app icon style, centered composition, no text, no letters, no typography. 
--ar 1:1 --v 6 --s 250 --q 2
```

**DALL-E / FLUX 提示词**
```
A high-quality 3D app icon logo. A bold compass ring with four directional points in deep blue metallic gradient. Inside the compass sits a glossy location pin icon with dark navy interior. Inside the pin, a glowing curved path with exactly 3 bright spherical nodes runs from bottom to top, gradient color from cyan to amber, soft neon bloom. Sparse constellation-like neural network lines with tiny dots in the dark background inside the pin. White background, 3D render, soft shadow, centered, no text, clean and modern.
```

---

## 方案二：扁平智航（2D 简约版）

**构图说明**

与方案一相同的「罗盘 + 定位标记 + 路径」骨架，但彻底扁平化，去除所有 3D、渐变、发光效果。用**纯色块 + 细线**重新诠释，更适合现代 Web 和印刷场景。路径上的 3 个节点用不同深浅的青绿色区分，背景神经网络改为极浅灰色的细线，若隐若现。

**Midjourney 提示词**
```
A flat minimalist logo icon in the style of modern SaaS apps. 
A thick circular compass outline with four small directional triangles, solid teal (#009688) stroke, 4px line weight. 
Centered inside: a solid location pin shape in dark blue (#003B57). 
Inside the pin: a simple curved line path with 3 solid white circles evenly spaced along it, representing three route options. 
Subtle light gray (#e2e8f0) constellation lines and dots in the background inside the pin, very faint, suggesting AI network. 
Pure white background, flat vector style, no gradients, no shadows, no 3D, no glow, geometric and clean, app icon grid, no text. 
--ar 1:1 --v 6 --s 150
```

---

## 方案三：双轨星航（突出双轨演化）

**构图说明**

在参考图基础上做项目特色强化：定位标记内部**不是一条路径，而是两条平行的发光细线**（一条直线代表经典算法，一条波浪线代表 LLM），两条线在终点汇合为一个共同的节点。背景神经网络比其他方案更密集，暗示「双轨」数据源共同驱动智能。外层罗盘增加了一个很 subtle 的**进度环/仪表盘刻度**，暗示「演化」和「学习」。

**核心卖点映射**
- 双线并行 → 行为 EMA + 对话 LLM 双轨更新
- 汇合节点 → 融合偏好 → 最终路线
- 密集星网 → 数据驱动 / 用户画像

**Midjourney 提示词**
```
A futuristic 3D app icon for an intelligent travel planner with dual-track learning. 
Outer compass ring in deep blue with a subtle dashboard刻度 texture on the inner edge. 
Center: a glossy dark location pin. 
Inside the pin: two parallel glowing tracks — one is a straight geometric line (cyan, representing classical algorithms), one is a smooth organic wave (amber, representing LLM), both converge and merge into a single bright white node at the top. 
Dense neural network mesh background with many small interconnected dots and lines inside the pin, glowing softly. 
White background, high-quality 3D render, soft ambient lighting, centered, no text, no letters. 
--ar 1:1 --v 6 --s 250
```

---

## 方案四：偏好光航（深色模式版）

**构图说明**

专为深色背景（GitHub Dark Mode、深色官网）设计的反白版本。整体采用**发光线条风格**而非实体填充：罗盘和定位标记由**霓虹线条**勾勒而成，内部路径是一条明亮的彩虹渐变光带（从青绿到琥珀），3 个节点是高亮的光晕圆球，背景神经网络像星空一样散布。整体看起来像暗夜里发光的导航信标。

**Midjourney 提示词**
```
A neon glow line-art logo on pure black background, designed for dark mode. 
A compass ring and location pin outline drawn with bright cyan (#00E5FF) neon tubes, 2px glow bloom. 
Inside the pin: a radiant winding path made of light, gradient from teal through yellow to amber, with 3 bright halo nodes along the path. 
Background: scattered tiny stars and faint constellation lines in soft blue, like a night sky map. 
High contrast, cyberpunk aesthetic, clean vector lines with glow effects, centered, no text, no fill shapes only glowing strokes and light. 
--ar 1:1 --v 6 --s 300
```

---

## 🎯 快速选用指南

| 你的使用场景 | 推荐方案 | 原因 |
|-------------|---------|------|
| **App Store / 应用启动图标** | 方案一：智航罗盘 | 3D 质感在图标网格中一眼突出 |
| **官网导航栏 / 页脚 / 印刷** | 方案二：扁平智航 | 扁平色块在任何尺寸都清晰，印刷成本低 |
| **技术博客 / 论文 / 路演 PPT** | 方案三：双轨星航 | 双线汇合是独特记忆点，适合讲故事 |
| **GitHub 深色模式 / 夜间主题官网** | 方案四：偏好光航 | 专为黑底设计，发光效果极具科技氛围 |

---

## 🛠️ 生成后处理

1. **去除文字污染**：AI 生图容易在罗盘刻度或背景处生成伪文字/乱码，导入 Figma 后务必擦除。
2. **提取主图形**：使用 Remove.bg 或 Photoshop 魔棒工具去除白色背景，获得带透明通道的 PNG。
3. **转矢量（可选）**：如需无限缩放，用 Vectorizer.AI 将 PNG 转为 SVG，再在 Illustrator 中精简锚点。
4. **多尺寸测试**：生成后缩放到 64×64、32×32、16×16，检查 3 颗节点是否依然可见。若不可见，将节点适当放大。
5. **圆角安全区**：若用于 iOS App Icon，确保图形位于 1024×1024 画布中央，四周留出至少 15% 的圆角安全边距。

---

## 🧩 配色速查（锁定项目色系）

| 角色 | 色值 | 在 Logo 中的用途 |
|------|------|----------------|
| 深蓝 | `#003B57` | 罗盘外框、定位标记主体、暗部 |
| 科技青 | `#009688` | 冷色节点、路径起点、2D 填充 |
| 荧光青 | `#00E5FF` | 发光效果、高光、科技感点缀 |
| 琥珀 | `#FFAB40` | 路径终点、强调节点、暖色对比 |
| 暗夜色 | `#0a192f` | 深色玻璃质感内部背景 |
