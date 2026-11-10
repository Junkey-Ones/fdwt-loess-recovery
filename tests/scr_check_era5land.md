# ERA5-Land M1／M2 测试

从仓库根目录执行 `python -m pytest tests/scr_check_era5land.py -q`。测试覆盖 SOP 的 U1–U3、E1–E4 所涉及的日界、符号、层厚、平闰年末候、缺测和闰年合成文件贯通，并验证修改原始文件后续接会被哈希校验阻断。合成 NetCDF 和 Parquet 位于 pytest 临时目录。正式全量原生文件验收由 M1 另行执行。
