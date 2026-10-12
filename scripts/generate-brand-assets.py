"""Generate deployment sizes from the shared, unmodified square brand artwork."""

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "shared/brand/icon-source.png"


def main() -> None:
    with Image.open(SOURCE) as source:
        image = source.convert("RGB")
        image.info.clear()
    if image.width != image.height:
        raise ValueError("Brand artwork must be square")

    def png(path: Path, size: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        image.resize((size, size), Image.Resampling.LANCZOS).save(path, optimize=True)

    web = ROOT / "web/assets/images"
    png(web / "brand-mark.png", 256)
    png(web / "favicon.png", 32)
    png(web / "apple-touch-icon.png", 180)
    review = ROOT / "review/campus_review/static"
    png(review / "brand-mark.png", 256)
    png(review / "favicon.png", 32)
    res = ROOT / "android/app/src/main/res"
    png(res / "drawable-nodpi/brand_mark.png", 256)
    for density, size in [("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)]:
        png(res / f"mipmap-{density}/ic_launcher.png", size)

    # Android's adaptive mask can crop 18dp on each side. The artwork's own
    # margins plus 10dp of canvas keep the tag and orange loop in the safe area.
    foreground = Image.new("RGBA", (432, 432), (0, 0, 0, 0))
    foreground.paste(image.resize((352, 352), Image.Resampling.LANCZOS), (40, 40))
    target = res / "drawable-nodpi/brand_launcher_foreground.png"
    foreground.save(target, optimize=True)


if __name__ == "__main__":
    main()
