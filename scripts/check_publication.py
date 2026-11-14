from hashlib import md5
from pathlib import Path
import re
import subprocess
import sys
import zipfile

patterns = (
    rb"(?i)[a-z]:[/\\]+(?:users|documents and settings)[/\\]+",
    rb"gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{25,}",
    rb"sk-(?:proj-)?[A-Za-z0-9_-]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
)
forbidden = {".env", ".key", ".pem", ".log", ".pkl", ".pyc", ".blend", ".gcode"}
text_suffixes = (".model", ".config", ".xml", ".rels", ".json", ".gcode")
def inspect(name, data):
    for pattern in patterns:
        if re.search(pattern, data):
            raise ValueError(f"Sensitive pattern in {name}")
    if name.endswith(".png") and any(
        kind in data[:4096] for kind in (b"eXIf", b"tEXt", b"iTXt", b"zTXt")
    ):
        # Parse actual chunks to avoid matching image payload bytes.
        offset = 8
        while offset + 8 <= len(data):
            length = int.from_bytes(data[offset:offset+4], "big")
            kind = data[offset+4:offset+8]
            if kind in (b"eXIf", b"tEXt", b"iTXt", b"zTXt"):
                raise ValueError(f"Image metadata in {name}")
            offset += 12 + length

def check_archive(path):
    with zipfile.ZipFile(path) as archive:
        if archive.testzip():
            raise ValueError(f"Invalid archive: {path}")
        names = {n.lower(): n for n in archive.namelist()}
        for name in names.values():
            if name.endswith(text_suffixes + (".png",)):
                inspect(f"{path}/{name}", archive.read(name))
            elif name.endswith(".md5"):
                body = archive.read(names[name.lower()[:-4]])
                if archive.read(name).decode().strip().lower() != md5(body).hexdigest():
                    raise ValueError(f"G-code checksum mismatch: {path}/{name}")
            else:
                raise ValueError(f"Unreviewed project entry: {path}/{name}")

paths = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
for name in filter(None, paths):
    path = Path(name)
    if path.suffix.lower() in forbidden or path.name.startswith(".env.") or path.name == "切片缓存位置.txt":
        raise ValueError(f"Local-only file tracked: {name}")
    if path.suffix == ".3mf":
        check_archive(path)
    elif path.resolve() != Path(__file__).resolve():
        inspect(name, path.read_bytes())
print("Publication check passed")
