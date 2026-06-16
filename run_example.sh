#!/usr/bin/env bash
# 便捷运行脚本。
# 用法一（批量，推荐）：把 .epro2 放进 input/ 后，直接运行：
#     ./run_example.sh
# 用法二（单文件）：
#     ./run_example.sh path/to/YourBoard.epro2
set -euo pipefail
cd "$(dirname "$0")"

# 优先尝试带图渲染；若未安装 matplotlib 则自动回退为不带图
if [ "$#" -ge 1 ]; then
    python3 -m epro2x.extract "$1" --diagrams || python3 -m epro2x.extract "$1"
else
    python3 -m epro2x.extract --diagrams || python3 -m epro2x.extract
fi

echo
echo "完成。请把 output/<工程名>/analysis.json 发给我做评审。"
