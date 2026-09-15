#include "CreateFactoryInputCommandlet.h"

#if WITH_EDITOR
#include "SmartFactoryPlayerController.h"
#include "SmartFactoryGameMode.h"
#include "InputAction.h"
#include "InputMappingContext.h"
#include "InputModifiers.h"
#include "InputCoreTypes.h"
#include "Kismet2/KismetEditorUtilities.h"
#include "Engine/Blueprint.h"
#include "Engine/BlueprintGeneratedClass.h"
#include "UObject/SavePackage.h"
#include "Misc/PackageName.h"

namespace
{
bool SaveInputAsset(UObject* Asset)
{
    Asset->MarkPackageDirty();
    FSavePackageArgs Args;
    Args.TopLevelFlags = RF_Public | RF_Standalone;
    return UPackage::SavePackage(
        Asset->GetOutermost(), Asset,
        *FPackageName::LongPackageNameToFilename(Asset->GetOutermost()->GetName(),
                                                 FPackageName::GetAssetPackageExtension()),
        Args);
}
} // namespace
#endif

int32 UCreateFactoryInputCommandlet::Main(const FString& Params)
{
#if WITH_EDITOR
    const FString ControllerPath = TEXT("/Game/SmartFactory/Blueprints/BP_SmartFactoryPlayerController");
    UBlueprint* ControllerBP =
        LoadObject<UBlueprint>(nullptr, *(ControllerPath + TEXT(".BP_SmartFactoryPlayerController")));
    if (!ControllerBP)
    {
        ControllerBP = FKismetEditorUtilities::CreateBlueprint(
            ASmartFactoryPlayerController::StaticClass(), CreatePackage(*ControllerPath),
            TEXT("BP_SmartFactoryPlayerController"), BPTYPE_Normal, UBlueprint::StaticClass(),
            UBlueprintGeneratedClass::StaticClass());
        FKismetEditorUtilities::CompileBlueprint(ControllerBP);
    }
    if (!ControllerBP->GeneratedClass || ControllerBP->Status == BS_Error)
    {
        return 1;
    }
    auto* Defaults =
        CastChecked<ASmartFactoryPlayerController>(ControllerBP->GeneratedClass->GetDefaultObject());
    const FString ContextPath = TEXT("/Game/SmartFactory/Input/IMC_Factory");
    auto* Context = LoadObject<UInputMappingContext>(nullptr, *(ContextPath + TEXT(".IMC_Factory")));
    const bool bNewContext = Context == nullptr;
    if (bNewContext)
    {
        Context = NewObject<UInputMappingContext>(CreatePackage(*ContextPath), TEXT("IMC_Factory"),
                                                  RF_Public | RF_Standalone);
    }
    auto Map = [&](UInputAction* Action, FKey Key, int32 Axis, bool bNegative)
    {
        if (!bNewContext)
        {
            return;
        }
        auto& Mapping = Context->MapKey(Action, Key);
        if (bNegative)
        {
            Mapping.Modifiers.Add(NewObject<UInputModifierNegate>(Context));
        }
        if (Axis != 0)
        {
            auto* Swizzle = NewObject<UInputModifierSwizzleAxis>(Context);
            Swizzle->Order = Axis == 1 ? EInputAxisSwizzle::YXZ : EInputAxisSwizzle::ZYX;
            Mapping.Modifiers.Add(Swizzle);
        }
    };
    for (int32 Index = 0; Index <= static_cast<int32>(EFactoryInput::Cancel); ++Index)
    {
        const auto Kind = static_cast<EFactoryInput>(Index);
        const FString Name = TEXT("IA_Factory") + StaticEnum<EFactoryInput>()->GetNameStringByValue(Index);
        const FString Path = TEXT("/Game/SmartFactory/Input/") + Name;
        auto* Action = LoadObject<UInputAction>(nullptr, *(Path + TEXT(".") + Name));
        if (!Action)
        {
            Action = NewObject<UInputAction>(CreatePackage(*Path), FName(*Name), RF_Public | RF_Standalone);
            Action->ValueType = Kind == EFactoryInput::Move
                                    ? EInputActionValueType::Axis3D
                                    : (Kind == EFactoryInput::Pointer
                                           ? EInputActionValueType::Axis2D
                                           : (Kind == EFactoryInput::Zoom ? EInputActionValueType::Axis1D
                                                                          : EInputActionValueType::Boolean));
            if (!SaveInputAsset(Action))
            {
                return 1;
            }
        }
        // 반대 방향 키를 동시에 누르면 상쇄하고 대각선 축은 합산합니다.
        if (Kind == EFactoryInput::Move || Kind == EFactoryInput::Pointer)
        {
            Action->AccumulationBehavior = EInputActionAccumulationBehavior::Cumulative;
            if (!SaveInputAsset(Action))
            {
                return 1;
            }
        }
        Defaults->FactoryInputActions.Add(Kind, Action);
        switch (Kind)
        {
        case EFactoryInput::Move:
            Map(Action, EKeys::W, 0, false);
            Map(Action, EKeys::S, 0, true);
            Map(Action, EKeys::D, 1, false);
            Map(Action, EKeys::A, 1, true);
            Map(Action, EKeys::E, 2, false);
            Map(Action, EKeys::Q, 2, true);
            break;
        case EFactoryInput::Pointer:
            Map(Action, EKeys::MouseX, 0, false);
            Map(Action, EKeys::MouseY, 1, false);
            break;
        case EFactoryInput::Zoom:
            Map(Action, EKeys::MouseWheelAxis, 0, false);
            break;
        case EFactoryInput::LookDrag:
            Map(Action, EKeys::RightMouseButton, 0, false);
            break;
        case EFactoryInput::PanDrag:
            Map(Action, EKeys::MiddleMouseButton, 0, false);
            break;
        case EFactoryInput::OrbitDrag:
            Map(Action, EKeys::LeftMouseButton, 0, false);
            break;
        case EFactoryInput::Fast:
            Map(Action, EKeys::LeftShift, 0, false);
            break;
        case EFactoryInput::Cell1:
            Map(Action, EKeys::One, 0, false);
            break;
        case EFactoryInput::Cell2:
            Map(Action, EKeys::Two, 0, false);
            break;
        case EFactoryInput::Cell3:
            Map(Action, EKeys::Three, 0, false);
            break;
        case EFactoryInput::Cell4:
            Map(Action, EKeys::Four, 0, false);
            break;
        case EFactoryInput::Run:
            Map(Action, EKeys::R, 0, false);
            break;
        case EFactoryInput::Pause:
            Map(Action, EKeys::P, 0, false);
            break;
        case EFactoryInput::Reset:
            Map(Action, EKeys::BackSpace, 0, false);
            break;
        case EFactoryInput::Emergency:
            Map(Action, EKeys::SpaceBar, 0, false);
            break;
        case EFactoryInput::Focus:
            Map(Action, EKeys::F, 0, false);
            break;
        case EFactoryInput::Overview:
            Map(Action, EKeys::Home, 0, false);
            break;
        case EFactoryInput::Cancel:
            Map(Action, EKeys::Escape, 0, false);
            break;
        }
    }
    Defaults->FactoryMappingContext = Context;
    if (!SaveInputAsset(Context) || !SaveInputAsset(ControllerBP))
    {
        return 1;
    }
    // 기존 게임모드의 다른 설정은 유지하고 컨트롤러 클래스만 연결합니다.
    auto* GameModeBP = LoadObject<UBlueprint>(
        nullptr, TEXT("/Game/SmartFactory/Blueprints/BP_SmartFactoryGameMode.BP_SmartFactoryGameMode"));
    if (!GameModeBP || !GameModeBP->GeneratedClass)
    {
        return 1;
    }
    auto* GameDefaults = CastChecked<ASmartFactoryGameMode>(GameModeBP->GeneratedClass->GetDefaultObject());
    GameDefaults->PlayerControllerClass = ControllerBP->GeneratedClass;
    if (!SaveInputAsset(GameModeBP))
    {
        return 1;
    }
    UE_LOG(LogTemp, Display, TEXT("FACTORY_INPUT_SAVED: actions=%d mappings=%d controller=%s"),
           Defaults->FactoryInputActions.Num(), Context->GetMappings().Num(), *ControllerBP->GetPathName());
    return 0;
#else
    return 1;
#endif
}
