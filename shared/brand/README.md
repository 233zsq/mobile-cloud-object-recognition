# 项目标识

`icon-source.png` 为用户提供的扫描标签图标。保留森林绿、奶油白和橙色，不重新绘制或改变构图。

运行 `python scripts/generate-brand-assets.py`（需要 Pillow）生成网页、README、App 页头和启动器使用的尺寸。网页标识为 256px，约 54KB；页头复用同一资源，避免加载原始大图。Android 自适应启动图标保留安全边距。

网页使用相同的标识、favicon 和主屏图标；README 直接引用网页标识，避免维护另一份副本。
