#pragma once

#include "CoreMinimal.h"
#include "GameFramework/PlayerController.h"
#include "SmartFactoryPlayerController.generated.h"

class ASmartFactoryCellActor;
class ACameraActor;
class USmartFactoryPanel;
class UInputAction;
class UInputMappingContext;
struct FInputActionValue;

// 입력 액션의 역할입니다. 키 배치는 IMC_Factory에서 편집합니다.
UENUM(BlueprintType)
enum class EFactoryInput : uint8
{
    Move,
    Pointer,
    Zoom,
    LookDrag,
    PanDrag,
    OrbitDrag,
    Fast,
    Cell1,
    Cell2,
    Cell3,
    Cell4,
    Run,
    Pause,
    Reset,
    Emergency,
    Focus,
    Overview,
    Cancel,
};

// 공장 카메라, 셀 선택, 운전 입력과 CommonUI 패널을 관리합니다.
UCLASS()
class SMARTFACTORY_API ASmartFactoryPlayerController : public APlayerController
{
    GENERATED_BODY()
public:
    virtual void SetupInputComponent() override;

    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Factory Input")
    TObjectPtr<UInputMappingContext> FactoryMappingContext;

    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Factory Input")
    TMap<EFactoryInput, TObjectPtr<UInputAction>> FactoryInputActions;

    // 카메라 이동 속도의 단위는 초당 센티미터입니다.
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Factory Camera|Speed", meta = (ClampMin = "0"))
    float CameraMoveSpeed = 650.0f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Factory Camera|Speed", meta = (ClampMin = "0"))
    float CameraFastMoveSpeed = 1800.0f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Factory Camera|Sensitivity",
              meta = (ClampMin = "0"))
    float LookSensitivity = 0.22f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Factory Camera|Sensitivity",
              meta = (ClampMin = "0"))
    float OrbitSensitivity = 0.22f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Factory Camera|Sensitivity",
              meta = (ClampMin = "0"))
    float PanSensitivity = 0.0015f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Factory Camera|Sensitivity",
              meta = (ClampMin = "0"))
    float ZoomSensitivity = 0.12f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Factory Camera|Limits", meta = (ClampMin = "0"))
    float MinPanSpeed = 0.3f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Factory Camera|Limits", meta = (ClampMin = "0"))
    float MaxPanSpeed = 10.0f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Factory Camera|Limits", meta = (ClampMin = "0"))
    float MinZoomStep = 35.0f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Factory Camera|Limits", meta = (ClampMin = "0"))
    float MaxZoomStep = 500.0f;
    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
    virtual void PlayerTick(float DeltaTime) override;
    void InitializeFactoryCamera(ACameraActor* Camera);
    TArray<ASmartFactoryCellActor*> GetFactoryCells() const;
    ASmartFactoryCellActor* GetSelectedCell() const;
    void SelectCell(int32 Index);
    void FocusSelectedCell();
    void ResetOverview();
    bool IsPointerOverPanel() const;
    bool VerifyCameraNavigation();
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly)
    int32 SelectedCellIndex = 0;

    UPROPERTY(EditDefaultsOnly, Category = "Factory UI")
    TSoftClassPtr<USmartFactoryPanel> PanelWidgetClass;

private:
    void TickEnhancedInputTest();
    int32 InputTestFrame = 0;
    int32 InputTestPhase = 0;
    bool bInputTestPassed = true;
    FVector InputTestPosition = FVector::ZeroVector;
    FRotator InputTestRotation = FRotator::ZeroRotator;
    float InputTestSavedSpeed = 0;
    float InputTestSavedFastSpeed = 0;
    bool bFastMovement = false;
    void HandleInput(const FInputActionValue& Value, EFactoryInput Kind);
    void ReleaseInput(const FInputActionValue& Value, EFactoryInput Kind);
    void BeginNavigation(int32 Mode);
    bool bUITestCompleted = false;
    bool bUITestPassed = false;
    // 저장된 CommonUI 위젯 블루프린트의 실행 인스턴스입니다.
    UPROPERTY(Transient)
    TObjectPtr<USmartFactoryPanel> FactoryPanel;
    UPROPERTY()
    TObjectPtr<ACameraActor> NavigationCamera;
    FTransform OverviewTransform;
    FVector OrbitFocus = FVector::ZeroVector;
    int32 DragMode = 0;
    FVector2D DragStart;
    void EndNavigation();
    void LookCamera(float X, float Y);
    void OrbitCamera(float X, float Y);
    void PanCamera(float X, float Y);
    void DollyCamera(float Amount);
};
