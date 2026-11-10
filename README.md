# 黄土高原骤旱恢复与极端降水接续（FD-WT）

本项目研究黄土高原土壤水分骤旱后的恢复时间、幅度和速率，极端降水在恢复前后何时接续，以及事件前冠层变化与深层土壤水状态如何关联这些结局。总体事件库计划覆盖 **2000–2023 年**，事件前五年 LAI 暴露分析计划覆盖 **2008–2023 年**。采用技术路线 V1.0 目录中的 **v1.3.1** 协议。

**当前可用的是架构预检。** 中文向导可核对模块依赖、运行别名、数据组合和输出路径。M0–M10 科学模块尚未接入生产入口。正式运行登记、输入哈希校验、冻结写入和续跑仍待实现。Snakemake 已安装，DAG 试运行尚未验收。

## 启动与验证

在已配置项目环境的 Windows 机器上，从仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe -m workflow.run_module
.\.venv\Scripts\python.exe -m pytest -q
```

第一条命令打开中文编号菜单。选择路线一、完整工作流或指定模块，输入 `YYYY-MM-DD_短描述` 格式的运行别名，再核对配置和路径后提交预检。第二条命令运行架构测试。

首次在其他机器上配置时，可从 [environment.yml](environment.yml) 创建 Conda 环境：

```powershell
conda env create -f environment.yml
conda activate fdwt-loess-recovery
python -m workflow.run_module
python -m pytest -q
```

## 数据与运行路线

原始数据按产品存放在 `data/raw/`，数据清单、覆盖缺口和获取入口见 [原始数据 README](data/raw/README.md)。目录盘点与 M1 正式验收分别记录。正式分析前还需冻结研究区边界和随机种子，验收现有数据并补齐对应分析所需输入。

| 模块 | 职责 |
| --- | --- |
| M0–M3 | 协议冻结、原始数据审计、时空与土层预处理、掩膜物候与气候态 |
| M4–M7 | 全量骤旱事件库、恢复和降水接续、事件前暴露、路线一统计 |
| M8 | 可退出的路线二三出口探索分析 |
| M9–M10 | 跨产品稳健性、独立复核和论文输出 |

路线一独立运行，M8 只在选定时进入下游汇总。依赖定义见 [DAG](workflow/dag.yaml)。

## 仓库导航

| 位置 | 内容 |
| --- | --- |
| `config/` | 科学参数、表结构、规范矩阵与偏离台账 |
| `metadata/` | 数据验收、协议冻结和运行登记 |
| `src/M0/` 至 `src/M10/` | 科学模块目录，目前为职责说明 |
| `workflow/` | 统一入口、依赖图、Snakemake 骨架和终端面板 |
| `data/interim/`、`data/frozen/` | 中间数据与冻结交接表 |
| `outputs/`、`logs/` | 运行结果与审计日志 |
| `tests/`、`docs/` | 架构测试、工程规范和研究协议 |

开发前阅读 [项目系统架构](docs/项目系统架构.md)和[脚本书写规范](docs/脚本书写规范.md)。研究口径见[预注册文档](docs/论文方向与构想/黄土高原FD-WT_v1.3.1_预注册文档.md)和[预处理 SOP](docs/论文方向与构想/黄土高原FD-WT_v1.3.1_分产品原生变量与预处理SOP附录.md)。AI 接手从 [AGENTS.md](AGENTS.md) 开始，Claude Code 通过 [CLAUDE.md](CLAUDE.md) 读取同一份说明。

## 版本管理与引用

提交源代码、测试、工作流、环境清单、科学配置、协议文档和可公开的登记表模板。原始数据、中间与冻结数据、输出、日志、虚拟环境、缓存和本机凭据按 [`.gitignore`](.gitignore) 排除。含受限站点信息或本机路径的登记副本放在 `metadata/local/`。

提交前用 `git status --short --untracked-files=all` 核对范围，用 `git check-ignore -v -- <路径>` 查询忽略规则。引用计算结果时记录协议版本、代码提交、完整 `run_id` 和数据产品版本。论文 DOI 和外部预注册编号待登记。
