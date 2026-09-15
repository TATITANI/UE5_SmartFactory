"""저장된 두 공장 레벨을 검사하는 호환 진입점입니다.

새 Unreal Python 커맨드릿에서 실행하며 Play나 에셋 저장을 하지 않습니다."""

from pathlib import Path
import runpy

folder = Path(__file__).resolve().parent
runpy.run_path(str(folder / "verify_static_factory.py"), run_name="__main__")
report = folder.parents[1] / "Saved/Tests"
(report / "EditorContentValidation.json").write_bytes(
    (report / "StaticFactoryValidation.json").read_bytes()
)
