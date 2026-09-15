#include "SmartFactoryGameMode.h"
#include "SmartFactoryPlayerController.h"
#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "Engine/PostProcessVolume.h"
#include "EngineUtils.h"
#include "SmartFactoryCellActor.h"

namespace
{
template <typename ActorType> ActorType* FindPlacedActor(UWorld* World)
{
    for (TActorIterator<ActorType> It(World); It; ++It)
    {
        return *It;
    }
    return nullptr;
}
} // namespace

ASmartFactoryGameMode::ASmartFactoryGameMode()
{
    PlayerControllerClass = ASmartFactoryPlayerController::StaticClass();
    HUDClass = nullptr;
    DefaultPawnClass = nullptr;
}

void ASmartFactoryGameMode::StartPlay()
{
    Super::StartPlay();
    for (TActorIterator<ASmartFactoryCellActor> It(GetWorld()); It; ++It)
    {
        Cell = *It;
        break;
    }
    if (!Cell)
    {
        UE_LOG(LogTemp, Error, TEXT("No authored BP_SmartFactoryCell is placed in this map."));
    }
    ACameraActor* Camera = nullptr;
    for (TActorIterator<ACameraActor> It(GetWorld()); It; ++It)
    {
        if (It->ActorHasTag(TEXT("SmartFactoryCamera")))
        {
            Camera = *It;
            break;
        }
    }
    if (!Camera)
    {
        Camera = FindPlacedActor<ACameraActor>(GetWorld());
    }
    if (!Camera)
    {
        Camera = GetWorld()->SpawnActor<ACameraActor>();
        const FVector CameraPosition(460, 570, 380);
        Camera->SetActorLocation(CameraPosition);
        Camera->SetActorRotation((FVector(-55, -35, 75) - CameraPosition).Rotation());
        Camera->GetCameraComponent()->SetFieldOfView(52.0f);
    }
    if (auto* PC = Cast<ASmartFactoryPlayerController>(GetWorld()->GetFirstPlayerController()))
    {
        PC->InitializeFactoryCamera(Camera);
    }
    // 조명은 맵에 저장되어 있으므로 Play에서 추가하지 않습니다.
    if (!FindPlacedActor<APostProcessVolume>(GetWorld()))
    {
        APostProcessVolume* Post = GetWorld()->SpawnActor<APostProcessVolume>();
        Post->bUnbound = true;
        Post->Settings.bOverride_AutoExposureMinBrightness = true;
        Post->Settings.bOverride_AutoExposureMaxBrightness = true;
        Post->Settings.AutoExposureMinBrightness = 1.0f;
        Post->Settings.AutoExposureMaxBrightness = 1.0f;
    }
    UE_LOG(LogTemp, Display,
           TEXT("FACTORY_UNREAL_READY: TCP 127.0.0.1:9847; awaiting authoritative Isaac state."));
}
