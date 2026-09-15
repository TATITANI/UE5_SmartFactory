#include "SmartFactoryPanel.h"
#include "Components/Button.h"
#include "Components/Slider.h"
#include "Components/TextBlock.h"
#include "IsaacBridgeComponent.h"
#include "SmartFactoryCellActor.h"
#include "SmartFactoryPlayerController.h"
#include "TimerManager.h"

void USmartFactoryPanel::NativeConstruct()
{
    Super::NativeConstruct();
    SetConsumePointerInput(false);
    if (UButton* Button = Cast<UButton>(GetWidgetFromName(TEXT("Cell1"))))
    {
        Button->OnClicked.AddUniqueDynamic(this, &ThisClass::Cell1);
    }
    if (UButton* Button = Cast<UButton>(GetWidgetFromName(TEXT("Cell2"))))
    {
        Button->OnClicked.AddUniqueDynamic(this, &ThisClass::Cell2);
    }
    if (UButton* Button = Cast<UButton>(GetWidgetFromName(TEXT("Cell3"))))
    {
        Button->OnClicked.AddUniqueDynamic(this, &ThisClass::Cell3);
    }
    if (UButton* Button = Cast<UButton>(GetWidgetFromName(TEXT("Cell4"))))
    {
        Button->OnClicked.AddUniqueDynamic(this, &ThisClass::Cell4);
    }
    if (UButton* Button = Cast<UButton>(GetWidgetFromName(TEXT("Run"))))
    {
        Button->OnClicked.AddUniqueDynamic(this, &ThisClass::Run);
    }
    if (UButton* Button = Cast<UButton>(GetWidgetFromName(TEXT("Pause"))))
    {
        Button->OnClicked.AddUniqueDynamic(this, &ThisClass::Pause);
    }
    if (UButton* Button = Cast<UButton>(GetWidgetFromName(TEXT("Reset"))))
    {
        Button->OnClicked.AddUniqueDynamic(this, &ThisClass::Reset);
    }
    if (UButton* Button = Cast<UButton>(GetWidgetFromName(TEXT("Emergency"))))
    {
        Button->OnClicked.AddUniqueDynamic(this, &ThisClass::Emergency);
    }
    if (UButton* Button = Cast<UButton>(GetWidgetFromName(TEXT("RunAll"))))
    {
        Button->OnClicked.AddUniqueDynamic(this, &ThisClass::RunAll);
    }
    if (UButton* Button = Cast<UButton>(GetWidgetFromName(TEXT("PauseAll"))))
    {
        Button->OnClicked.AddUniqueDynamic(this, &ThisClass::PauseAll);
    }
    if (UButton* Button = Cast<UButton>(GetWidgetFromName(TEXT("Slower"))))
    {
        Button->OnClicked.AddUniqueDynamic(this, &ThisClass::Slower);
    }
    if (UButton* Button = Cast<UButton>(GetWidgetFromName(TEXT("Faster"))))
    {
        Button->OnClicked.AddUniqueDynamic(this, &ThisClass::Faster);
    }
    if (USlider* Slider = Cast<USlider>(GetWidgetFromName(TEXT("Speed"))))
    {
        Slider->OnMouseCaptureBegin.AddUniqueDynamic(this, &ThisClass::SpeedBegin);
        Slider->OnMouseCaptureEnd.AddUniqueDynamic(this, &ThisClass::SpeedEnd);
    }
    GetWorld()->GetTimerManager().SetTimer(RefreshTimer, this, &ThisClass::Refresh, 0.05f, true);
    Refresh();
}

void USmartFactoryPanel::NativeDestruct()
{
    GetWorld()->GetTimerManager().ClearTimer(RefreshTimer);
    Super::NativeDestruct();
}

bool USmartFactoryPanel::IsPointerOverPanel() const
{
    const UWidget* Panel = GetWidgetFromName(TEXT("Panel"));
    return Panel && Panel->IsHovered();
}

UIsaacBridgeComponent* USmartFactoryPanel::SelectedBridge() const
{
    const auto* Controller = Cast<ASmartFactoryPlayerController>(GetOwningPlayer());
    const auto* Cell = Controller ? Controller->GetSelectedCell() : nullptr;
    return Cell ? Cell->GetBridge() : nullptr;
}

void USmartFactoryPanel::SendSelected(const FString& Command)
{
    if (auto* Bridge = SelectedBridge())
    {
        Bridge->SendCommand(Command);
    }
}

void USmartFactoryPanel::SendAll(const FString& Command)
{
    if (auto* Controller = Cast<ASmartFactoryPlayerController>(GetOwningPlayer()))
    {
        for (auto* Cell : Controller->GetFactoryCells())
        {
            Cell->GetBridge()->SendCommand(Command);
        }
    }
}

void USmartFactoryPanel::Refresh()
{
    const auto* Bridge = SelectedBridge();
    const bool bLive = Bridge && Bridge->bConnected && Bridge->bHasFreshState;
    auto SetText = [this](const TCHAR* Name, const FString& Value)
    {
        if (auto* Label = Cast<UTextBlock>(GetWidgetFromName(Name)))
        {
            Label->SetText(FText::FromString(Value));
        }
    };
    const auto* Controller = Cast<ASmartFactoryPlayerController>(GetOwningPlayer());
    SetText(TEXT("Status"),
            FString::Printf(TEXT("CELL %02d / %s"), Controller ? Controller->SelectedCellIndex + 1 : 1,
                            bLive ? TEXT("LIVE") : TEXT("OFFLINE")));
    SetText(TEXT("Mode"),
            Bridge ? Bridge->Mode.ToUpper() + TEXT(" / ") + Bridge->Phase.ToUpper() : TEXT("WAITING"));
    SetText(TEXT("Counts"),
            FString::Printf(TEXT("SORTED %d   RED %d   BLUE %d"), Bridge ? Bridge->SortedCount : 0,
                            Bridge ? Bridge->RedCount : 0, Bridge ? Bridge->BlueCount : 0));
    SetText(TEXT("Telemetry"),
            FString::Printf(TEXT("SIM %.1f s / BELT %.2f m/s"), Bridge ? Bridge->SimulationTime : 0.0,
                            Bridge ? Bridge->EffectiveConveyorSpeed : 0.0));
    SetText(TEXT("Command"), Bridge ? Bridge->LastCommandStatus : TEXT("Waiting for Isaac Sim"));
    if (auto* Slider = Cast<USlider>(GetWidgetFromName(TEXT("Speed"))))
    {
        // 셀 변경 또는 연결 단절 시 이전 셀의 드래그 값을 전송하지 않습니다.
        if (!Bridge || SpeedPort != Bridge->Port || !bLive)
        {
            bDraggingSpeed = false;
            SpeedPort = Bridge ? Bridge->Port : -1;
        }
        Slider->SetIsEnabled(bLive);
        if (!bDraggingSpeed)
        {
            Slider->SetValue(Bridge ? Bridge->ConveyorSpeedSetpoint : 0.35);
        }
        SetText(TEXT("Setpoint"), FString::Printf(TEXT("SPEED SETPOINT %.2f m/s"), Slider->GetValue()));
    }
    for (const FName Name : {FName("Run"), FName("Pause"), FName("Reset"), FName("Slower"), FName("Faster")})
    {
        if (UWidget* Button = GetWidgetFromName(Name))
        {
            Button->SetIsEnabled(bLive);
        }
    }
}
void USmartFactoryPanel::Cell1()
{
    if (auto* Controller = Cast<ASmartFactoryPlayerController>(GetOwningPlayer()))
    {
        Controller->SelectCell(0);
        Refresh();
    }
}
void USmartFactoryPanel::Cell2()
{
    if (auto* Controller = Cast<ASmartFactoryPlayerController>(GetOwningPlayer()))
    {
        Controller->SelectCell(1);
        Refresh();
    }
}
void USmartFactoryPanel::Cell3()
{
    if (auto* Controller = Cast<ASmartFactoryPlayerController>(GetOwningPlayer()))
    {
        Controller->SelectCell(2);
        Refresh();
    }
}
void USmartFactoryPanel::Cell4()
{
    if (auto* Controller = Cast<ASmartFactoryPlayerController>(GetOwningPlayer()))
    {
        Controller->SelectCell(3);
        Refresh();
    }
}
void USmartFactoryPanel::Run()
{
    SendSelected(TEXT("resume"));
}
void USmartFactoryPanel::Pause()
{
    SendSelected(TEXT("pause"));
}
void USmartFactoryPanel::Reset()
{
    SendSelected(TEXT("reset"));
}
void USmartFactoryPanel::Emergency()
{
    SendAll(TEXT("emergency_stop"));
}
void USmartFactoryPanel::RunAll()
{
    SendAll(TEXT("resume"));
}
void USmartFactoryPanel::PauseAll()
{
    SendAll(TEXT("pause"));
}
void USmartFactoryPanel::Slower()
{
    if (auto* Bridge = SelectedBridge())
    {
        Bridge->SendConveyorSpeed(FMath::Clamp(Bridge->ConveyorSpeedSetpoint - 0.05, 0.05, 1.0));
    }
}
void USmartFactoryPanel::Faster()
{
    if (auto* Bridge = SelectedBridge())
    {
        Bridge->SendConveyorSpeed(FMath::Clamp(Bridge->ConveyorSpeedSetpoint + 0.05, 0.05, 1.0));
    }
}
void USmartFactoryPanel::SpeedBegin()
{
    bDraggingSpeed = true;
}

bool USmartFactoryPanel::VerifyControls()
{
    // 실제 생성된 디자이너 버튼과 이벤트 연결 및 셀 선택 경로를 검사합니다.
    for (const FName Name : {FName("Cell1"), FName("Cell2"), FName("Cell3"), FName("Cell4"), FName("Run"),
                             FName("Pause"), FName("Reset"), FName("Emergency"), FName("RunAll"),
                             FName("PauseAll"), FName("Slower"), FName("Faster")})
    {
        const auto* Button = Cast<UButton>(GetWidgetFromName(Name));
        if (!Button || !Button->OnClicked.IsBound())
        {
            return false;
        }
    }
    const auto* Slider = Cast<USlider>(GetWidgetFromName(TEXT("Speed")));
    if (!Slider || !Slider->OnMouseCaptureBegin.IsBound() || !Slider->OnMouseCaptureEnd.IsBound())
    {
        return false;
    }
    auto* Controller = Cast<ASmartFactoryPlayerController>(GetOwningPlayer());
    if (!Controller || Controller->GetFactoryCells().Num() != 4)
    {
        return false;
    }
    for (int32 Index = 0; Index < 4; ++Index)
    {
        auto* Button =
            CastChecked<UButton>(GetWidgetFromName(FName(*FString::Printf(TEXT("Cell%d"), Index + 1))));
        Button->OnClicked.Broadcast();
        if (Controller->SelectedCellIndex != Index)
        {
            return false;
        }
    }
    Controller->SelectCell(0);
    Refresh();
    return true;
}

void USmartFactoryPanel::SpeedEnd()
{
    if (bDraggingSpeed)
    {
        if (auto* Bridge = SelectedBridge())
        {
            if (Bridge->Port == SpeedPort)
            {
                if (auto* Slider = Cast<USlider>(GetWidgetFromName(TEXT("Speed"))))
                {
                    Bridge->SendConveyorSpeed(Slider->GetValue());
                }
            }
        }
    }
    bDraggingSpeed = false;
}
