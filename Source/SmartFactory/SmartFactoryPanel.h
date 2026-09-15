#pragma once

#include "CommonUserWidget.h"
#include "CoreMinimal.h"
#include "SmartFactoryPanel.generated.h"

class UIsaacBridgeComponent;

// 공장 운전 패널의 동작을 담당하며 배치는 위젯 블루프린트에 저장합니다.
UCLASS(Abstract, Blueprintable)
class SMARTFACTORY_API USmartFactoryPanel : public UCommonUserWidget
{
    GENERATED_BODY()
public:
    bool IsPointerOverPanel() const;
    bool VerifyControls();

protected:
    virtual void NativeConstruct() override;
    virtual void NativeDestruct() override;

private:
    FTimerHandle RefreshTimer;
    bool bDraggingSpeed = false;
    int32 SpeedPort = -1;
    UIsaacBridgeComponent* SelectedBridge() const;
    void Refresh();
    void SendSelected(const FString& Command);
    void SendAll(const FString& Command);
    UFUNCTION()
    void Cell1();
    UFUNCTION()
    void Cell2();
    UFUNCTION()
    void Cell3();
    UFUNCTION()
    void Cell4();
    UFUNCTION()
    void Run();
    UFUNCTION()
    void Pause();
    UFUNCTION()
    void Reset();
    UFUNCTION()
    void Emergency();
    UFUNCTION()
    void RunAll();
    UFUNCTION()
    void PauseAll();
    UFUNCTION()
    void Slower();
    UFUNCTION()
    void Faster();
    UFUNCTION()
    void SpeedBegin();
    UFUNCTION()
    void SpeedEnd();
};
