#include "../SmartFactoryPlayerController.h"

#include "Camera/CameraActor.h"
#include "EnhancedInputComponent.h"
#include "EnhancedPlayerInput.h"
#include "InputAction.h"
#include "InputMappingContext.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"

// 실제 Enhanced Player Input에 액션을 주입하여 바인딩부터 카메라 변환까지 검사합니다.
// 운전 명령은 전송하지 않으므로 실행 중인 Isaac 공정에 영향을 주지 않습니다.
void ASmartFactoryPlayerController::TickEnhancedInputTest()
{
    if (GetWorld()->GetTimeSeconds() < 2.0f)
    {
        return;
    }
    auto* Enhanced = Cast<UEnhancedPlayerInput>(PlayerInput);
    auto Check = [this](bool bValue, const TCHAR* Message)
    {
        bInputTestPassed &= bValue;
        UE_LOG(LogTemp, Display, TEXT("FACTORY_INPUT_CHECK %s: %s"), Message,
               bValue ? TEXT("PASS") : TEXT("FAIL"));
    };
    if (!Enhanced || !NavigationCamera || FactoryInputActions.Num() != 18 || !FactoryMappingContext)
    {
        Check(false, TEXT("Blueprint input configuration"));
        FPlatformMisc::RequestExitWithStatus(false, 1);
        return;
    }
    auto Inject = [&](EFactoryInput Kind, const FInputActionValue& Value)
    {
        Enhanced->InjectInputForAction(FactoryInputActions.FindChecked(Kind), Value);
    };
    if (InputTestFrame == 0)
    {
        if (InputTestPhase == 0)
        {
            Check(GetClass()->HasAnyClassFlags(CLASS_CompiledFromBlueprint), TEXT("Blueprint child active"));
            Check(FactoryMappingContext->GetMappings().Num() == 24, TEXT("Saved key mappings"));
            Check(Cast<UEnhancedInputComponent>(InputComponent) != nullptr, TEXT("Enhanced component"));
            InputTestSavedSpeed = CameraMoveSpeed;
            InputTestSavedFastSpeed = CameraFastMoveSpeed;
            ResetOverview();
        }
        if (InputTestPhase == 2)
        {
            Check(FVector::Distance(InputTestPosition, NavigationCamera->GetActorLocation()) > 1,
                  TEXT("Move action moves camera"));
            CameraMoveSpeed = 0;
        }
        if (InputTestPhase == 3)
        {
            Check(NavigationCamera->GetActorLocation().Equals(InputTestPosition, 0.001),
                  TEXT("Editable zero speed stops translation"));
            CameraFastMoveSpeed = 900;
        }
        if (InputTestPhase == 4)
        {
            Check(FVector::Distance(InputTestPosition, NavigationCamera->GetActorLocation()) > 1,
                  TEXT("Fast action uses separate speed"));
        }
        if (InputTestPhase == 5)
        {
            Check(!NavigationCamera->GetActorRotation().Equals(InputTestRotation, 0.01),
                  TEXT("Pointer action rotates camera"));
        }
        if (InputTestPhase == 6)
        {
            Check(DragMode == 0 && !bFastMovement, TEXT("Completed input releases navigation"));
        }
        if (InputTestPhase == 7)
        {
            Check(SelectedCellIndex == 3, TEXT("Cell action selects fourth cell"));
        }
        if (InputTestPhase == 8)
        {
            Check(FVector::Distance(InputTestPosition, NavigationCamera->GetActorLocation()) > 1,
                  TEXT("Zoom action moves camera"));
        }
        if (InputTestPhase == 9)
        {
            Check(NavigationCamera->GetActorTransform().Equals(OverviewTransform, 0.01),
                  TEXT("Overview action restores camera"));
            CameraMoveSpeed = InputTestSavedSpeed;
            CameraFastMoveSpeed = InputTestSavedFastSpeed;
            SelectCell(0);
            FFileHelper::SaveStringToFile(
                bInputTestPassed ? TEXT("{\"success\":true,\"actions\":18,\"mappings\":24}")
                                 : TEXT("{\"success\":false}"),
                *(FPaths::ProjectSavedDir() / TEXT("Tests/EnhancedInputValidation.json")));
            FPlatformMisc::RequestExitWithStatus(false, bInputTestPassed ? 0 : 1);
            return;
        }
        InputTestPosition = NavigationCamera->GetActorLocation();
        InputTestRotation = NavigationCamera->GetActorRotation();
    }
    if (InputTestPhase <= 4)
    {
        Inject(EFactoryInput::LookDrag, FInputActionValue(true));
    }
    if (InputTestPhase >= 1 && InputTestPhase <= 3)
    {
        Inject(EFactoryInput::Move, FInputActionValue(FVector(1, 0, 0)));
    }
    if (InputTestPhase == 3)
    {
        Inject(EFactoryInput::Fast, FInputActionValue(true));
    }
    if (InputTestPhase == 4)
    {
        Inject(EFactoryInput::Pointer, FInputActionValue(FVector2D(5, 2)));
    }
    if (InputTestPhase == 6 && InputTestFrame == 0)
    {
        Inject(EFactoryInput::Cell4, FInputActionValue(true));
    }
    if (InputTestPhase == 7 && InputTestFrame == 0)
    {
        Inject(EFactoryInput::Zoom, FInputActionValue(1.0f));
    }
    if (InputTestPhase == 8 && InputTestFrame == 0)
    {
        Inject(EFactoryInput::Overview, FInputActionValue(true));
    }
    ++InputTestFrame;
    if (InputTestFrame >= 6)
    {
        InputTestFrame = 0;
        ++InputTestPhase;
    }
}
