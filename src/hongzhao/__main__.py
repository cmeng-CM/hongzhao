# 支持 python -m hongzhao 调用（与 console script hongzhao 同入口）
from hongzhao.cli import main

raise SystemExit(main())
