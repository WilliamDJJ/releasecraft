# Downloads

[English overview](../README.md) · [中文说明](../README.zh-CN.md) · [Release guide](RELEASING.md)

## Official release

**Releasecraft 1.0.0** is distributed under the first public Git tag **v1.0**.
Use the [official release page](https://github.com/WilliamDJJ/releasecraft/releases/tag/v1.0)
and [source repository](https://github.com/WilliamDJJ/releasecraft).
Older internal version labels are not prior public releases.

All platform bundles contain the same wheel. Python 3.11+ with pip and venv is required; the
native desktop window also requires Tk. No Python interpreter or paid service is bundled.

## Windows

- [Download Windows ZIP](https://github.com/WilliamDJJ/releasecraft/releases/download/v1.0/releasecraft-1.0.0-windows.zip)
- Extract and double-click `Start Releasecraft.cmd` for offline installation and the desktop window
- CLI alternative: `install.cmd`, then `releasecraft.cmd --help`

## Linux

- [Download Linux tar.gz](https://github.com/WilliamDJJ/releasecraft/releases/download/v1.0/releasecraft-1.0.0-linux.tar.gz)
- Run `sh install.sh`, then `sh releasecraft-gui.sh` in a graphical session with Tk
- CLI alternative: `sh releasecraft.sh --help`

## Source and wheel

- [Source ZIP](https://github.com/WilliamDJJ/releasecraft/releases/download/v1.0/releasecraft-1.0.0-source.zip): repository root with tests, documentation and packaging scripts
- [Universal wheel](https://github.com/WilliamDJJ/releasecraft/releases/download/v1.0/releasecraft-1.0.0-py3-none-any.whl): shared installable wheel

## Verify before installation

Download [SHA256SUMS](https://github.com/WilliamDJJ/releasecraft/releases/download/v1.0/SHA256SUMS)
and the [hash-bound validation report](https://github.com/WilliamDJJ/releasecraft/releases/download/v1.0/VALIDATION.md)
from the same release. Compare every SHA-256 digit before installation. Checksums establish integrity
relative to that file, not publisher identity. The validation report must bind the same artifact hashes.

```powershell
Get-FileHash .\releasecraft-1.0.0-windows.zip -Algorithm SHA256
```

```sh
sha256sum -c SHA256SUMS
```

The Linux command expects all listed artifacts in the current directory. For one downloaded file,
compute `sha256sum filename` and compare its entry. GitHub's automatic source downloads are separate
from the tested `releasecraft-1.0.0-source.zip` asset; their archive bytes and checksums differ.

## 中文提示

请从[官方 v1.0 发布页](https://github.com/WilliamDJJ/releasecraft/releases/tag/v1.0)选择 Windows、Linux、源码或 wheel 文件，并同时下载 `SHA256SUMS` 和 `VALIDATION.md`。
Python 包版本为 1.0.0。平台包不包含 Python；桌面窗口需要 Tk，命令行可单独使用。
GitHub 自动生成的源码下载与经过验证的 `releasecraft-1.0.0-source.zip` 附件不是同一归档，不能混用校验和。
