"""第 13 章 可靠性｜Runnable.with_retry / with_fallbacks + 幂等 + 熔断 + recursion_limit。"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.context import Context
from common.lc_academy import CHAPTERS, chapter_04_resume
ID = Path(__file__).resolve().parent.name

def run(payload=None, ctx=None):
    return CHAPTERS[ID](payload or {}, ctx or Context(ID))

def resume(case_id, action, approver="李四（主管）", ctx=None):
    return chapter_04_resume(case_id, action, approver, ctx or Context(ID))

if __name__ == "__main__":
    print(json.dumps(run(json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}), ensure_ascii=False, indent=2))
