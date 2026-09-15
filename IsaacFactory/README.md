# Isaac Factory — 컨베이어와 로봇팔 분류 셀

컨베이어로 들어오는 빨강·파랑 제품을 로봇팔이 집어 색상별 적재 위치로 옮기는 Isaac Sim 공정 데모입니다. 각 셀이 한 번에 제품 하나를 처리하며, 컨베이어 이송 → 접근 → 집기 → 상승 → 이동 → 내려놓기 → 해제 → 복귀를 반복합니다. Unreal 공장 홀에서는 셀 4개가 독립적으로 동작하고, 기존 단독 실행은 셀 1개를 사용합니다. ROS 2 연동은 이번 범위에서 제외했습니다.

이 프로젝트는 **공정 순서와 제어 구조를 확인하는 시연용 모델**입니다. 로봇팔은 해석적 역기구학(IK)으로 자세를 계산하는 기구학 모델이고, 집기는 제품을 도구 목표 위치에 붙이는 이상적 결합으로 표현합니다. 접촉, 마찰, 파지력, 토크, 충돌 회피 또는 실제 설비 안전성을 검증하는 모델은 아닙니다. 색상 분류와 픽업 센서는 내부 상태·위치로 계산하며 카메라 인식 결과가 아닙니다.

## 실행 환경

기본 Isaac Sim 설치 경로는 `D:\IsaacSim\4.5.0`입니다. 프로젝트 코드는 `D:\UnrealProjects\SmartFactory\IsaacFactory`에 있습니다. Unreal 연동은 프로젝트 루트의 `Launch-Integrated-Factory.bat`로 실행합니다. 두 엔진은 별도 프로세스에서 TCP로 상태와 명령을 주고받으며, [Unreal 연동 안내](../UNREAL_INTEGRATION.md)에 역할과 조작 방법을 정리했습니다. 아래 `Launch-Factory.bat`는 Isaac 단독 화면을 실행합니다.

RTX 3070 / VRAM 8 GB에 맞춰 **Isaac Sim 4.5.0**을 사용합니다. NVIDIA가 공개한 4.5 최소 사양은 RTX 3070, VRAM 8 GB, RAM 32 GB, SSD 여유 공간 50 GB 및 Windows 10/11입니다. 2026년 9월 기준 최신 6.1 계열의 최소 GPU 사양은 RTX 4080 / VRAM 16 GB이므로 이 컴퓨터에서는 4.5를 선택했습니다. 4.5에는 Python 3.10이 포함되어 있습니다. [4.5 요구 사양](https://docs.isaacsim.omniverse.nvidia.com/4.5.0/installation/requirements.html), [최신 요구 사양](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/requirements.html), [4.5 Python 환경](https://docs.isaacsim.omniverse.nvidia.com/4.5.0/installation/install_python.html).

설치를 다시 준비해야 할 때 PowerShell에서 실행합니다.

```powershell
Set-Location 'D:\UnrealProjects\SmartFactory\IsaacFactory'
.\scripts\Install-IsaacSim.ps1
```

설치 스크립트는 NVIDIA 공식 ZIP을 `downloads`에 이어받고 빈 설치 폴더에 압축을 풉니다. 파일 크기를 확인하고 `local-install.json`에 다운로드 주소와 로컬 SHA256을 기록합니다. 기록한 해시는 로컬 파일 식별용이며 NVIDIA가 공개한 서명·해시와 대조했다는 의미는 아닙니다. 완료 표식과 실행 파일이 있는 설치는 유지하며, 이 설치기가 남긴 중단 표식이 있으면 압축 풀기를 다시 시도합니다. [공식 다운로드 목록](https://docs.isaacsim.omniverse.nvidia.com/4.5.0/installation/download.html).

## 시작하기

### Unreal 공장 홀: 독립 셀 4개

프로젝트의 기본 Unreal 레벨은 36 × 24 m의 `L_SmartFactoryHall`이며, 컨베이어와 로봇팔 작업 셀 4개를 배치합니다. `Launch-Integrated-Factory.bat`는 `run_factory_multi.py`를 사용하는 멀티 셀 연동 실행입니다. 기존 `L_SmartFactory`와 아래의 Isaac 1셀 단독 실행은 유지합니다.

멀티 실행기는 하나의 `SimulationApp` 안에 `/World/FactoryCell01`부터 `FactoryCell04`까지의 USD 루트와 독립 제어기를 만듭니다. 포트는 `9847~9850`이며, 스냅샷은 각 셀의 로컬 미터 좌표를 유지합니다. Unreal 원점 `(-800,-450,0)`, `(0,-450,0)`, `(800,-450,0)`, `(0,450,0) cm`에 대응하는 Isaac 원점은 `(-8,4.5,0)`, `(0,4.5,0)`, `(8,4.5,0)`, `(0,-4.5,0) m`입니다.

```powershell
& 'D:\IsaacSim\4.5.0\python.bat' 'D:\UnrealProjects\SmartFactory\IsaacFactory\run_factory_multi.py' --headless --serve --base-port 9847 --export --output 'D:\UnrealProjects\SmartFactory\IsaacFactory\outputs\unreal-multi' --stop-file 'D:\UnrealProjects\SmartFactory\Saved\FactoryMulti.stop'
```

시작 속도는 순서대로 `0.25`, `0.35`, `0.45`, `0.30 m/s`입니다. `FactoryController.set_conveyor_speed(value)`와 TCP 명령 `set_conveyor_speed`의 `value`로 `0.05~1.0 m/s`를 설정합니다. 이동 중 제품 위치를 유지하고 이후 속도만 바꾸며, 정지 중 변경해도 공정을 재개하지 않습니다. RESET도 설정 속도를 유지합니다. 스냅샷의 `conveyor_speed_setpoint`는 설정 속도, `conveyor_speed`는 현재 유효 속도이며 로봇 작업 단계·정지 상태에서는 0입니다.

멀티 출력 폴더에 약 2초마다 갱신하는 통합 `report.json`, 셀별 `cell01~cell04/telemetry.jsonl`, 종료 시 셀별 보고서가 생깁니다. `--export`는 시작과 정상 종료 때 `factory_hall.usda`를 저장합니다. 지정한 종료 요청 파일을 만들면 최종 저장 후 정상 종료합니다. 요청 파일은 남으므로 다음 실행 전에 정리하거나 새 경로를 사용합니다. `--steps N`은 제한된 검사 실행, `--dry-run`은 Isaac 장면 없이 네 포트와 제어기를 검사할 때 사용합니다. headless·serve 실행은 Isaac 뷰포트 갱신을 중지하지만 USD·IK는 유지합니다.

PowerShell 래퍼 `scripts/Run-Factory-Multi.ps1 -Headless -Serve -Export`는 고유한 종료 요청 경로를 만들고 출력 폴더의 `launch.json`에 기록합니다. 정식 통합 런처의 메타데이터는 프로젝트 루트의 `Saved/Logs/IsaacMultiBackend.json`입니다. 해당 기록의 `stop_file`을 생성하면 그 실행의 정상 종료를 요청합니다.

Unreal의 자유 카메라, 셀 선택, 속도 슬라이더, 전체 비상정지와 실행·종료 방법은 [Unreal 연동 안내](../UNREAL_INTEGRATION.md)를 참고합니다. 실제 Isaac·Unreal 공장 홀 통합 검사 9개가 통과했으며, 상세 결과와 최종 마감 후 검증 기록도 그 안내에서 확인합니다.

### Isaac 단독 화면: 셀 1개

바탕화면의 `SmartFactory - Isaac Sim` 바로가기 또는 `Launch-Factory.bat`를 더블클릭하면 기본 GUI 데모를 시작합니다. 첫 실행은 셰이더 준비 때문에 시간이 걸릴 수 있습니다. 명령으로 실행하려면 다음과 같이 사용합니다.

```powershell
Set-Location 'D:\UnrealProjects\SmartFactory\IsaacFactory'
.\scripts\Run-Factory.ps1
```

자동 실행과 산출물 저장 예시:

```powershell
.\scripts\Run-Factory.ps1 -Cycles 4 -Capture -Export
.\scripts\Run-Factory.ps1 -Headless -Cycles 4 -Fast -Capture -Export
.\scripts\Run-Factory.ps1 -DryRun -Cycles 24 -Fast
```

`Launch-Factory.bat`에도 같은 PowerShell 옵션을 전달할 수 있습니다. 다른 Isaac Sim 설치 경로는 `-IsaacPath 'D:\다른경로'`로 지정합니다.

| PowerShell 옵션 | Python 옵션 | 용도 |
| --- | --- | --- |
| `-IsaacPath` | 해당 없음 | `python.bat`가 있는 Isaac Sim 설치 경로 |
| `-Headless` | `--headless` | GUI 창 없이 실행. Isaac Sim 렌더링에는 GPU가 필요합니다. |
| `-Cycles N` | `--cycles N` | 지정한 제품 처리 사이클을 완료하면 종료 |
| `-Steps N` | `--steps N` | 지정한 업데이트 횟수에 도달하면 종료 |
| `-Fast` | `--fast` | 실시간 진행을 위한 대기를 생략 |
| `-Capture` | `--capture` | Isaac Sim 뷰포트 PNG 저장 |
| `-Export` | `--export` | Isaac Sim 장면을 USDA로 저장 |
| `-DryRun` | `--dry-run` | Isaac Sim을 시작하지 않고 Python 공정 코어만 실행 |

기본 GUI 실행은 적재 공간이 찰 때까지 반복한 후 정지합니다. 창 없는 실행은 분류함이 가득 차면 종료하며, `-Cycles` 또는 `-Steps`로 더 짧게 실행할 수 있습니다. `-DryRun`은 3D 렌더링·IK·Isaac Sim 동작을 검증하지 않으며 PNG와 USDA도 생성하지 않습니다. PowerShell 실행기는 `-DryRun`에서도 기본적으로 설치된 Isaac Sim의 Python을 사용합니다.

## 공정 제어

제어 패널에서 일시정지, 재개, 비상정지와 초기화를 조작합니다.

| 조작 | 동작 |
| --- | --- |
| PAUSE | 진행 시간과 제품·로봇 목표 자세를 고정 |
| RUN / RESUME | 일시정지 지점부터 계속 진행 |
| EMERGENCY STOP | 비상정지를 유지하며 자세와 집기 상태를 보존. Resume으로 해제되지 않음 |
| RESET CELL | 제품, 카운터와 비상정지를 초기화하고 일시정지 상태로 복귀 |
| EXPORT USD | 현재 장면을 `outputs/factory.usda`에 저장 |

초기화 후에는 Resume으로 시작합니다. 화면의 E-STOP은 데모 상태 제어 기능입니다.

다음 제품의 적재 위치가 가득 차면 복귀 동작을 마친 뒤 `BIN_FULL` 상태로 멈춥니다. Resume으로 이 상태를 해제할 수 없으며 RESET CELL로 적재물과 카운터를 비운 뒤 재개합니다.

## 설정과 출력

`config/factory.json`에서 벨트 시작점·픽업점·속도, 로봇 기준 위치와 홈 위치, 제품 크기·색상 순서, 적재 위치·간격, 단계별 소요 시간을 조정합니다. 모든 길이는 미터, 시간은 초이며 Z축이 위쪽인 월드 좌표를 사용합니다. 벨트·적재 좌표는 표면 높이, 제품 위치는 박스 중심입니다. 로봇 목표점은 박스 중심보다 `grasp_offset`만큼 위에 있습니다.

설정값 검사는 숫자·양수·좌표 길이 등을 확인합니다. 설정을 바꾼 뒤에는 로봇 도달 범위와 장면의 간섭을 별도로 확인해야 합니다. 벨트 프레임·작업대·바닥 등의 장식 형상은 기본 배치에 맞춘 고정 크기이므로 크게 재배치할 때에는 `factory_scene.py`도 함께 조정합니다. 기본 적재 패턴은 색상별 3×3 슬롯·2층(`max_layers: 2`)으로, 색상별 18개·총 36개를 처리할 수 있습니다. `-Cycles`에 설정된 수용량보다 큰 값을 요청하면 실행 전에 오류를 반환합니다.

실행 결과는 기본적으로 `outputs` 폴더에 저장합니다. 같은 출력 경로로 다시 실행하면 로그와 보고서를 덮어씁니다. PNG·USDA는 해당 저장 옵션을 사용한 실행에서 갱신하므로 이전 실행의 파일과 혼동하지 않도록 확인합니다.

| 파일 | 내용 |
| --- | --- |
| `telemetry.jsonl` | 단계·모드·적재 수가 바뀔 때와 시뮬레이션 시간 약 0.5초 간격으로 기록하는 상태 스냅샷 |
| `report.json` | 실행 종료 시점의 요약 정보 |
| `factory.usda` | `-Export` 사용 시 저장하는 USD 장면 |
| `factory.png` | `-Capture` 사용 시 저장하는 뷰포트 이미지 |

USDA는 저장 시점의 장면입니다. 공정 제어를 실행하려면 `Launch-Factory.bat` 또는 `run_factory.py`를 사용합니다. PNG는 두 제품이 적재된 시점, 짧은 실행이면 종료 시점의 뷰포트를 저장합니다. 보고서의 `mode`로 GUI·headless·코어 전용 실행을 구별할 수 있으며 `capture_ok`로 캡처 결과를 확인합니다.

직접 `run_factory.py`를 실행하면 `--config`, `--output`, `--dt`도 지정할 수 있습니다. 실행기의 작업 폴더는 Isaac Sim 설치 경로이므로 추가 경로에는 절대 경로를 사용합니다. 예를 들어 실행별 출력 폴더를 분리하려면:

```powershell
& 'D:\IsaacSim\4.5.0\python.bat' 'D:\UnrealProjects\SmartFactory\IsaacFactory\run_factory.py' --cycles 4 --capture --export --output 'D:\UnrealProjects\SmartFactory\IsaacFactory\outputs\trial-01'
```

기본 시간 간격 `--dt`는 1/60초이며 허용 범위는 `0 < dt <= 0.1`입니다. `--cycles`와 `--steps`를 함께 지정하면 먼저 도달한 조건에서 종료합니다. `--dry-run`에 종료 조건을 생략하면 기본 6사이클을 실행합니다.

## 개발 구조와 이후 ROS 2 확장

`factory_core.py`는 표준 라이브러리만 사용하는 결정적 공정 상태 머신입니다. `FactoryController.update(dt)`로 진행하고 `snapshot()`으로 JSON 직렬화 가능한 상태를 읽습니다. Isaac Sim과 통신 라이브러리를 코어에 넣지 않아 독립적으로 테스트할 수 있습니다.

Isaac Sim 어댑터는 코어의 월드 좌표 목표를 받아 로봇 자세와 3D 장면을 갱신합니다. 향후 ROS 2를 추가할 때에는 이 경계에서 명령 입력과 상태 출력을 연결하고, 실제 관절 상태·접촉 피드백을 반영하는 어댑터를 별도로 구현하는 구조입니다. 현재 ROS 노드, 토픽, DDS, MoveIt 설정은 포함하지 않으며 실행 시 ROS 브리지를 사용하지 않습니다. Isaac Sim 배포판에 포함된 ROS 관련 파일이 존재하는 것과 브리지를 실행하는 것은 별개입니다.

Isaac Sim 실행의 텔레메트리와 최종 보고서에는 `robot_joint_state`가 추가됩니다. `names`는 `base_yaw`, `shoulder`, `elbow`, `wrist_pitch`이며 `positions`는 라디안 단위의 **계산된 관절 명령값**입니다. `reachable`과 `reach_error`는 IK 도달 가능 여부와 미터 단위 목표 오차입니다. 이는 센서나 PhysX가 측정한 관절 피드백이 아니며, 코어 전용 실행에는 포함되지 않습니다.

코어 테스트는 공정 단계 경계, 반복 분류·적재, 시간 간격 분할 일관성, 일시정지·재개, 비상정지 유지·초기화, 상태 복사와 잘못된 설정을 검사합니다. 이 테스트가 통과해도 물리 기반 파지나 실제 로봇 동작이 검증된 것은 아닙니다.

## 확인된 검사와 재실행

2026년 9월 13일 NVIDIA 공식 4.5 호환성 검사기를 이 컴퓨터에서 실행한 결과는 `PASSED`였습니다. 검사기가 보고한 GPU는 RTX 3070, 드라이버는 591.86, VRAM은 8.59 GB(충족, 추가 용량 권장), RAM은 68.45 GB이며 Windows 11 Home 25H2를 지원 대상으로 판정했습니다. 상세 결과는 `outputs/compatibility-check.log`에 있습니다. 이 판정은 시스템 요구 사항 검사 결과이며 전체 공정의 렌더링·물리 동작 검증 결과가 아닙니다.

호환성 검사 재실행:

```powershell
Set-Location 'D:\UnrealProjects\SmartFactory\IsaacFactory\runtime\compatibility-check'
.\omni.isaac.sim.compatibility_check.bat --no-window --/app/quitAfter=15 --/log/level=info
```

설치된 Isaac Sim Python 환경에서 현재 전체 테스트 **39개가 통과**했습니다. 기본 36사이클 도달 가능성, TCP 처리, 네 셀 독립 제어, 속도 변경 연속성, 정상 종료 요청을 포함합니다. 이전 1셀 구성에서는 실제 RTX 렌더링 4사이클과 PNG·USD 저장도 확인했습니다. 당시 기록은 [VALIDATION.md](VALIDATION.md)에 있으며, 새 4셀 홀의 GPU 통합 검증과는 구분합니다. 재실행 명령은 다음과 같습니다. `tests`를 찾을 수 있도록 프로젝트 폴더에서 실행합니다.

```powershell
Set-Location 'D:\UnrealProjects\SmartFactory\IsaacFactory'
& 'D:\IsaacSim\4.5.0\python.bat' -m unittest discover -s tests -v
```

## 참고 문서

- [NVIDIA Isaac Sim 4.5 워크스테이션 설치](https://docs.isaacsim.omniverse.nvidia.com/4.5.0/installation/install_workstation.html)
- [Isaac Sim 컨베이어 유틸리티](https://docs.isaacsim.omniverse.nvidia.com/4.5.0/digital_twin/warehouse_logistics/ext_isaacsim_asset_gen_conveyor.html)
- [Franka 로봇과 Pick/Place 공식 예제](https://docs.isaacsim.omniverse.nvidia.com/4.5.0/core_api_tutorials/tutorial_core_adding_manipulator.html)
- [Isaac Sim 4.5 ROS 브리지 설정](https://docs.isaacsim.omniverse.nvidia.com/4.5.0/installation/install_ros.html#choosing-the-ros-bridge-version-in-isaac-sim-sh)
- [Omniverse 뷰포트 캡처 API](https://docs.omniverse.nvidia.com/kit/docs/omni.kit.viewport.utility/1.0.19/USAGE_PYTHON.html)

참고 문서의 Franka와 컨베이어 예제는 이후 물리 모델 확장에 활용할 수 있습니다. 현재 데모의 로봇은 자체 생성한 기구학 시연 모델입니다.
