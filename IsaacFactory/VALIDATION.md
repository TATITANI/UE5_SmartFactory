# 실행 검증 — 2026-09-13

- 설치: NVIDIA Isaac Sim 4.5.0, `D:\IsaacSim\4.5.0`.
- 환경: Windows 11 Home, i5-13600K, RAM 64 GB, RTX 3070 8 GB, NVIDIA 드라이버 591.86.
- NVIDIA 공식 호환성 검사: **PASSED**, 종료 코드 0. 로그: `outputs/compatibility-check.log`.
- 설치된 Isaac Sim Python 환경에서 단위 테스트 **16개 통과**. 로그: `outputs/unit-tests.log`.
- 전체 36회 공정 제어 검사: 빨강 18개·파랑 18개 적재 후 `bin_full` 정지. 보고서: `outputs/capacity-check/report.json`.
- 실제 Isaac Sim Vulkan/RTX 렌더링: **4사이클 통과**, 빨강 2개·파랑 2개, 403 업데이트, 시뮬레이션 시간 40.3초. 보고서: `outputs/isaac-smoke/report.json`.
- 실제 장면의 PNG 캡처와 USDA 저장 성공. `outputs/isaac-smoke/factory.png`, `outputs/isaac-smoke/factory.usda`.
- 실행 시 ROS 1·ROS 2 브리지가 비활성 상태임을 확인했습니다.
- GUI 실행: `Isaac Sim Python 4.5.0` 창이 응답하는 상태이며, 조작 패널을 생성하고 4개 이상 분류하는 상태 기록을 확인했습니다. 로그: `outputs/interactive.log`.
- 바탕화면에 `SmartFactory - Isaac Sim` 실행 바로가기를 생성했습니다.

첫 실행은 셰이더 컴파일을 포함해 약 266초가 걸렸습니다. 단위 테스트는 일시정지·재개, 비상정지 래치, 초기화, 분류함 용량, 시간 간격에 따른 일관성, 전체 분류 경로의 IK 도달 범위를 검사합니다.

현재 모델은 기구학 공정 데모이며 제품은 이상적인 집기 방식으로 이동합니다. 위 검증 결과는 마찰·접촉·토크 또는 물리적 파지 성공률 검증을 뜻하지 않습니다.

![Isaac Sim 실제 실행 화면](outputs/isaac-smoke/factory.png)
