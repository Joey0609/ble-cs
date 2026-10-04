# IPIN 2026 中文演示稿

主题：从信道探测到智能戒指运动轨迹。保留原稿的 34 页主讲内容、55 页下钻讲解与 3 页参考附录，共 92 页；正文、讲者备注、图示、交互结果与导航均提供中文。

在线地址：<https://joey0609.github.io/ble-cs/ipin2026-tutorial/>。

本稿采用 Reveal.js 网页演示形式，没有构建步骤。需联网加载演示框架、公式库与字体。英文缩写保留标准写法：悬停带虚线的缩写可查看英文全称和中文释义；页脚“缩写全称与中文”打开完整术语表，各页讲者备注也列出所用缩写。品牌、型号、设备标识、命令与公式变量保持原始写法。

应用截图仍使用原图，图上中文通过可编辑文字层显示；曲线与数值没有重绘。模拟数据标识继续保留。点击截图可放大查看。来源、素材与许可见 `sources.html`，原始项目见 <https://github.com/Sens-Wear/ble-cs>。

## 本地查看

在本目录运行：

```sh
npm start
```

默认打开 <http://localhost:8023/tutorial-IPIN2026/>。也可在仓库根目录运行：

```sh
python -m http.server 8023 --directory docs
```

网页必须通过 HTTP 打开，直接打开本地 HTML 文件无法加载各页内容。

## 演示与导出

← / → 切换主讲页；↓ / ↑ 查看下钻讲解或显示、隐藏答案。S 打开讲者视图，O 或 Esc 查看总览，F 进入全屏。访问 `index.html?print-pdf` 后在 Chrome 中打印为 PDF；加上 `&showNotes=true` 可附带讲者备注。

## 发布

在 `Joey0609/ble-cs` 的设置中将 GitHub Pages 来源设为 GitHub Actions，再手动运行 `.github/workflows/publish-tutorial.yml`，选择 `main`。该工作流仅在手动触发时部署，普通推送不会自动发布。

翻译相关文件：`slides/` 保存正文与讲者备注；`slides.json` 保存顺序与导航；`terminology.js` 保存缩写释义；`screenshot-labels.json` 与 `screenshot-translations.js` 保存中文截图标注；`interactives.js` 保存交互演示与中文结果文本。
