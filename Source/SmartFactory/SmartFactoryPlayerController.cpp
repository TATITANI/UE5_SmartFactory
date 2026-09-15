#include "SmartFactoryPlayerController.h"

#include "Camera/CameraActor.h"
#include "EngineUtils.h"
#include "InputCoreTypes.h"
#include "IsaacBridgeComponent.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "SmartFactoryCellActor.h"
#include "SmartFactoryPanel.h"
#include "UnrealClient.h"
#include "EnhancedInputComponent.h"
#include "EnhancedInputSubsystems.h"
#include "InputMappingContext.h"
#include "InputAction.h"
#include "Engine/LocalPlayer.h"

void ASmartFactoryPlayerController::BeginPlay()
{
    Super::BeginPlay();
    EndNavigation();
    if (ULocalPlayer* LocalPlayer = GetLocalPlayer())
    {
        if (auto* Subsystem = LocalPlayer->GetSubsystem<UEnhancedInputLocalPlayerSubsystem>())
        {
            if (FactoryMappingContext)
            {
                Subsystem->AddMappingContext(FactoryMappingContext, 0);
            }
        }
    }
    UClass* PanelClass = PanelWidgetClass.LoadSynchronous();
    if (PanelClass)
    {
        FactoryPanel = CreateWidget<USmartFactoryPanel>(this, PanelClass);
        FactoryPanel->AddToViewport();
    }
    else
    {
        UE_LOG(LogTemp, Error, TEXT("WBP_FactoryPanel is missing from /Game/SmartFactory/UI."));
    }
}

void ASmartFactoryPlayerController::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    if (FactoryPanel)
    {
        FactoryPanel->RemoveFromParent();
        FactoryPanel = nullptr;
    }
    if (ULocalPlayer* LocalPlayer = GetLocalPlayer())
    {
        if (auto* Subsystem = LocalPlayer->GetSubsystem<UEnhancedInputLocalPlayerSubsystem>())
        {
            if (FactoryMappingContext)
            {
                Subsystem->RemoveMappingContext(FactoryMappingContext);
            }
        }
    }
    Super::EndPlay(EndPlayReason);
}

TArray<ASmartFactoryCellActor*> ASmartFactoryPlayerController::GetFactoryCells() const
{
    TArray<ASmartFactoryCellActor*> Cells;
    for (TActorIterator<ASmartFactoryCellActor> It(GetWorld()); It; ++It)
    {
        Cells.Add(*It);
    }
    Cells.Sort(
        [](const ASmartFactoryCellActor& A, const ASmartFactoryCellActor& B)
        {
            return A.GetBridge()->Port == B.GetBridge()->Port ? A.GetName() < B.GetName()
                                                              : A.GetBridge()->Port < B.GetBridge()->Port;
        });
    return Cells;
}

ASmartFactoryCellActor* ASmartFactoryPlayerController::GetSelectedCell() const
{
    const auto Cells = GetFactoryCells();
    return Cells.IsValidIndex(SelectedCellIndex) ? Cells[SelectedCellIndex]
                                                 : (Cells.Num() ? Cells[0] : nullptr);
}

void ASmartFactoryPlayerController::SelectCell(int32 Index)
{
    if (GetFactoryCells().IsValidIndex(Index))
    {
        SelectedCellIndex = Index;
    }
}

void ASmartFactoryPlayerController::InitializeFactoryCamera(ACameraActor* Camera)
{
    NavigationCamera = Camera;
    OverviewTransform = Camera->GetActorTransform();
    OrbitFocus = FVector::ZeroVector;
    SetViewTarget(Camera);
}

bool ASmartFactoryPlayerController::IsPointerOverPanel() const
{
    return FactoryPanel && FactoryPanel->IsPointerOverPanel();
}

void ASmartFactoryPlayerController::EndNavigation()
{
    const bool bWasDragging = DragMode != 0;
    DragMode = 0;
    bShowMouseCursor = true;
    FInputModeGameAndUI Input;
    Input.SetHideCursorDuringCapture(false);
    Input.SetLockMouseToViewportBehavior(EMouseLockMode::DoNotLock);
    SetInputMode(Input);
    if (bWasDragging)
    {
        SetMouseLocation(DragStart.X, DragStart.Y);
    }
}

void ASmartFactoryPlayerController::LookCamera(float X, float Y)
{
    if (!NavigationCamera)
    {
        return;
    }
    FRotator Rotation = NavigationCamera->GetActorRotation();
    Rotation.Yaw += X * LookSensitivity;
    Rotation.Pitch = FMath::Clamp(Rotation.Pitch + Y * LookSensitivity, -85.f, 85.f);
    Rotation.Roll = 0;
    NavigationCamera->SetActorRotation(Rotation);
    const double Distance =
        FMath::Max(200.0, FVector::Distance(NavigationCamera->GetActorLocation(), OrbitFocus));
    OrbitFocus = NavigationCamera->GetActorLocation() + Rotation.Vector() * Distance;
}

void ASmartFactoryPlayerController::OrbitCamera(float X, float Y)
{
    if (!NavigationCamera)
    {
        return;
    }
    const double Distance =
        FMath::Max(100.0, FVector::Distance(NavigationCamera->GetActorLocation(), OrbitFocus));
    FRotator Rotation = (OrbitFocus - NavigationCamera->GetActorLocation()).Rotation();
    Rotation.Yaw += X * OrbitSensitivity;
    Rotation.Pitch = FMath::Clamp(Rotation.Pitch + Y * OrbitSensitivity, -85.f, 80.f);
    Rotation.Roll = 0;
    NavigationCamera->SetActorLocationAndRotation(OrbitFocus - Rotation.Vector() * Distance, Rotation);
}

void ASmartFactoryPlayerController::PanCamera(float X, float Y)
{
    if (!NavigationCamera)
    {
        return;
    }
    const double Scale =
        FMath::Clamp(FVector::Distance(NavigationCamera->GetActorLocation(), OrbitFocus) * PanSensitivity,
                     double(MinPanSpeed), double(MaxPanSpeed));
    const FVector Delta =
        (-NavigationCamera->GetActorRightVector() * X - NavigationCamera->GetActorUpVector() * Y) * Scale;
    NavigationCamera->AddActorWorldOffset(Delta);
    OrbitFocus += Delta;
}

void ASmartFactoryPlayerController::DollyCamera(float Amount)
{
    if (!NavigationCamera)
    {
        return;
    }
    const double Distance = FVector::Distance(NavigationCamera->GetActorLocation(), OrbitFocus);
    double Step = FMath::Clamp(Distance * ZoomSensitivity, double(MinZoomStep), double(MaxZoomStep)) * Amount;
    if (Step > 0)
    {
        Step = FMath::Min(Step, FMath::Max(0.0, Distance - 80.0));
    }
    NavigationCamera->AddActorWorldOffset(NavigationCamera->GetActorForwardVector() * Step);
}

void ASmartFactoryPlayerController::FocusSelectedCell()
{
    const auto* Selected = GetSelectedCell();
    if (!NavigationCamera || !Selected)
    {
        return;
    }
    OrbitFocus = Selected->GetActorTransform().TransformPosition(FVector(0, -35, 85));
    const FVector Offset(560, 670, 490);
    NavigationCamera->SetActorLocationAndRotation(OrbitFocus + Offset, (-Offset).Rotation());
}

void ASmartFactoryPlayerController::ResetOverview()
{
    if (NavigationCamera)
    {
        NavigationCamera->SetActorTransform(OverviewTransform);
    }
    OrbitFocus = FVector::ZeroVector;
}

bool ASmartFactoryPlayerController::VerifyCameraNavigation()
{
    if (!NavigationCamera || !GetSelectedCell())
    {
        return false;
    }
    ResetOverview();
    const FTransform Original = NavigationCamera->GetActorTransform();
    LookCamera(50, 15);
    const bool LookChanged = !NavigationCamera->GetActorRotation().Equals(Original.Rotator(), .01);
    const FVector BeforeOrbit = NavigationCamera->GetActorLocation();
    OrbitCamera(40, -10);
    const bool OrbitChanged = FVector::Distance(BeforeOrbit, NavigationCamera->GetActorLocation()) > 1;
    const FVector BeforePan = NavigationCamera->GetActorLocation();
    PanCamera(30, 15);
    const bool PanChanged = FVector::Distance(BeforePan, NavigationCamera->GetActorLocation()) > 1;
    const FVector BeforeZoom = NavigationCamera->GetActorLocation();
    DollyCamera(1);
    const bool ZoomChanged = FVector::Distance(BeforeZoom, NavigationCamera->GetActorLocation()) > 1;
    FocusSelectedCell();
    const bool FocusChanged =
        FVector::Distance(Original.GetLocation(), NavigationCamera->GetActorLocation()) > 1;
    ResetOverview();
    return LookChanged && OrbitChanged && PanChanged && ZoomChanged && FocusChanged &&
           NavigationCamera->GetActorTransform().Equals(Original, .01);
}

void ASmartFactoryPlayerController::PlayerTick(float DeltaTime)
{
    Super::PlayerTick(DeltaTime);
    if (FParse::Param(FCommandLine::Get(), TEXT("FactoryInputTest")))
    {
        TickEnhancedInputTest();
        return;
    }
    if (FParse::Param(FCommandLine::Get(), TEXT("FactoryUITest")))
    {
        if (GetWorld()->GetTimeSeconds() > 5.0f && !bUITestCompleted)
        {
            bUITestCompleted = true;
            bUITestPassed = FactoryPanel && FactoryPanel->VerifyControls();
            FFileHelper::SaveStringToFile(
                bUITestPassed ? TEXT("{\"success\":true,\"common_user_widget\":true,\"cell_selection\":true,"
                                     "\"bound_buttons\":12}")
                              : TEXT("{\"success\":false}"),
                *(FPaths::ProjectSavedDir() / TEXT("Tests/CommonUIValidation.json")));
            FScreenshotRequest::RequestScreenshot(FPaths::ProjectSavedDir() / TEXT("Tests/CommonUI.png"),
                                                  true, false);
        }
        if (GetWorld()->GetTimeSeconds() > 8.0f)
        {
            FPlatformMisc::RequestExitWithStatus(false, bUITestPassed ? 0 : 1);
        }
        return;
    }
}

void ASmartFactoryPlayerController::SetupInputComponent()
{
    Super::SetupInputComponent();
    auto* EnhancedInput = Cast<UEnhancedInputComponent>(InputComponent);
    if (!ensureMsgf(EnhancedInput, TEXT("EnhancedInputComponent is required")))
    {
        return;
    }
    for (const auto& Entry : FactoryInputActions)
    {
        if (!Entry.Value)
        {
            continue;
        }
        const bool bAxis = Entry.Key == EFactoryInput::Move || Entry.Key == EFactoryInput::Pointer ||
                           Entry.Key == EFactoryInput::Zoom;
        EnhancedInput->BindAction(Entry.Value, bAxis ? ETriggerEvent::Triggered : ETriggerEvent::Started,
                                  this, &ThisClass::HandleInput, Entry.Key);
        EnhancedInput->BindAction(Entry.Value, ETriggerEvent::Completed, this, &ThisClass::ReleaseInput,
                                  Entry.Key);
        EnhancedInput->BindAction(Entry.Value, ETriggerEvent::Canceled, this, &ThisClass::ReleaseInput,
                                  Entry.Key);
    }
}

void ASmartFactoryPlayerController::BeginNavigation(int32 Mode)
{
    if (!NavigationCamera || DragMode != 0 || IsPointerOverPanel())
    {
        return;
    }
    DragMode = Mode;
    float MouseX = 0;
    float MouseY = 0;
    GetMousePosition(MouseX, MouseY);
    DragStart = FVector2D(MouseX, MouseY);
    bShowMouseCursor = false;
    FInputModeGameOnly Input;
    Input.SetConsumeCaptureMouseDown(false);
    // 입력 모드 변경 시 누른 마우스 버튼의 상태를 유지합니다.
    SetInputMode(Input);
}

void ASmartFactoryPlayerController::ReleaseInput(const FInputActionValue& Value, EFactoryInput Kind)
{
    if (Kind == EFactoryInput::Fast)
    {
        bFastMovement = false;
    }
    if ((Kind == EFactoryInput::LookDrag && DragMode == 1) ||
        (Kind == EFactoryInput::PanDrag && DragMode == 2) ||
        (Kind == EFactoryInput::OrbitDrag && DragMode == 3))
    {
        EndNavigation();
    }
}

void ASmartFactoryPlayerController::HandleInput(const FInputActionValue& Value, EFactoryInput Kind)
{
    if (Kind == EFactoryInput::Emergency)
    {
        for (auto* Cell : GetFactoryCells())
        {
            Cell->GetBridge()->SendCommand(TEXT("emergency_stop"));
        }
        return;
    }
    if (Kind == EFactoryInput::Cancel)
    {
        EndNavigation();
        return;
    }
    if (Kind == EFactoryInput::Fast)
    {
        bFastMovement = true;
        return;
    }
    if (Kind == EFactoryInput::LookDrag || Kind == EFactoryInput::PanDrag || Kind == EFactoryInput::OrbitDrag)
    {
        BeginNavigation(Kind == EFactoryInput::LookDrag ? 1 : (Kind == EFactoryInput::PanDrag ? 2 : 3));
        return;
    }
    if (Kind == EFactoryInput::Move)
    {
        if (NavigationCamera && DragMode == 1)
        {
            const FVector Axis = Value.Get<FVector>();
            FVector Move = NavigationCamera->GetActorForwardVector() * Axis.X +
                           NavigationCamera->GetActorRightVector() * Axis.Y + FVector::UpVector * Axis.Z;
            Move = Move.GetClampedToMaxSize(1.0) * GetWorld()->GetDeltaSeconds() *
                   (bFastMovement ? CameraFastMoveSpeed : CameraMoveSpeed);
            NavigationCamera->AddActorWorldOffset(Move);
            OrbitFocus += Move;
        }
        return;
    }
    if (Kind == EFactoryInput::Pointer)
    {
        const FVector2D Axis = Value.Get<FVector2D>();
        if (DragMode == 1)
        {
            LookCamera(Axis.X, Axis.Y);
        }
        else if (DragMode == 2)
        {
            PanCamera(Axis.X, Axis.Y);
        }
        else if (DragMode == 3)
        {
            OrbitCamera(Axis.X, Axis.Y);
        }
        return;
    }
    if (Kind == EFactoryInput::Zoom)
    {
        if (!IsPointerOverPanel())
        {
            DollyCamera(Value.Get<float>());
        }
        return;
    }
    if (DragMode != 0)
    {
        return;
    }
    if (Kind >= EFactoryInput::Cell1 && Kind <= EFactoryInput::Cell4)
    {
        SelectCell(static_cast<int32>(Kind) - static_cast<int32>(EFactoryInput::Cell1));
    }
    else if (Kind == EFactoryInput::Focus)
    {
        FocusSelectedCell();
    }
    else if (Kind == EFactoryInput::Overview)
    {
        ResetOverview();
    }
    else if (auto* Cell = GetSelectedCell())
    {
        if (Kind == EFactoryInput::Run)
        {
            Cell->GetBridge()->SendCommand(TEXT("resume"));
        }
        else if (Kind == EFactoryInput::Pause)
        {
            Cell->GetBridge()->SendCommand(TEXT("pause"));
        }
        else if (Kind == EFactoryInput::Reset)
        {
            Cell->GetBridge()->SendCommand(TEXT("reset"));
        }
    }
}
