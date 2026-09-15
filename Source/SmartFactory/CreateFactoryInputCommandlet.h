#pragma once

#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "CreateFactoryInputCommandlet.generated.h"

// Enhanced Input 에셋과 카메라 설정용 컨트롤러 자식을 저장합니다.
UCLASS()
class UCreateFactoryInputCommandlet : public UCommandlet
{
    GENERATED_BODY()
public:
    virtual int32 Main(const FString& Params) override;
};
