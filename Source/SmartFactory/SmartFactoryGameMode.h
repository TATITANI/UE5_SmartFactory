#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "SmartFactoryGameMode.generated.h"

class ASmartFactoryCellActor;

/** Unreal은 셀을 표시하고 조작하며 Isaac 프로세스가 공정 상태를 결정합니다. */
UCLASS()
class SMARTFACTORY_API ASmartFactoryGameMode : public AGameModeBase
{
    GENERATED_BODY()
public:
    ASmartFactoryGameMode();
    virtual void StartPlay() override;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly)
    TObjectPtr<ASmartFactoryCellActor> Cell;
};
