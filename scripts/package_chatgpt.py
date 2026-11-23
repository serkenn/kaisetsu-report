"""Claude と ChatGPT に登録する kaisetu.zip をリポジトリ直下に作る。"""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def main():
    root = Path(__file__).resolve().parents[1]
    skill = root / ".claude" / "skills" / "kaisetu"
    files = {
        "SKILL.md": skill / "SKILL.md",
        "scripts/kaisetu_build.py": skill / "scripts" / "kaisetu_build.py",
        "LICENSE": root / "LICENSE",
    }
    for directory in ("assets", "references"):
        for path in (skill / directory).iterdir():
            if path.is_file() and not path.name.startswith("."):
                files[path.relative_to(skill).as_posix()] = path

    with ZipFile(root / "kaisetu.zip", "w") as archive:
        for name, path in sorted(files.items()):
            entry = ZipInfo(f"kaisetu/{name}")
            archive.writestr(entry, path.read_bytes(), compress_type=ZIP_DEFLATED)


if __name__ == "__main__":
    main()
