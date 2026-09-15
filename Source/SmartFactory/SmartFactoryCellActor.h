#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "SmartFactoryCellActor.generated.h"

class UIsaacBridgeComponent;
class UMaterialInterface;
class UStaticMesh;
class UStaticMeshComponent;
class FJsonObject;

/** Isaac의 기준 공정 상태를 기구학적으로 표시합니다. 자체 공정 및 물리 계산은 없습니다. */
UCLASS()
class SMARTFACTORY_API ASmartFactoryCellActor : public AActor
{
    GENERATED_BODY()

public:
    ASmartFactoryCellActor();
    virtual void Tick(float DeltaSeconds) override;
    /** Floor, Grid, Black, Belt, Slats, Steel 등의 키로 저장된 재질을 참조합니다. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Isaac Factory|Assets")
    TMap<FName, TObjectPtr<UMaterialInterface>> MaterialPalette;

    /** 저장된 블루프린트 컴포넌트를 연결하며 형상을 생성하거나 제거하지 않습니다. */
    UFUNCTION(BlueprintCallable, CallInEditor, Category = "Isaac Factory")
    void BindAuthoredComponents();

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Isaac Factory")
    TObjectPtr<UIsaacBridgeComponent> Bridge;

    UFUNCTION(BlueprintPure, Category = "Isaac Factory")
    UIsaacBridgeComponent* GetBridge() const
    {
        return Bridge;
    }

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Isaac Factory")
    bool bSceneReady = false;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Isaac Factory")
    int32 RenderedProductCount = 0;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Isaac Factory")
    FVector ToolWorldPosition = FVector::ZeroVector;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Isaac Factory")
    double ToolReachErrorMeters = 0.0;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Isaac Factory")
    int32 AuthoredComponentCount = 0;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Isaac Factory")
    bool bProductPoolOverflow = false;

    /** Isaac 미터 좌표(오른손, Z 위쪽)를 Unreal 센티미터 좌표(왼손, Z 위쪽)로 변환합니다. */
    static FVector IsaacToUnreal(const FVector& Metres);

protected:
    virtual void BeginPlay() override;

private:
    TMap<FName, UStaticMeshComponent*> Arm;
    TArray<UStaticMeshComponent*> ProductPool;
    TArray<UStaticMeshComponent*> BeltSlats;
    TArray<UStaticMeshComponent*> Signals;
    UStaticMeshComponent* Sensor = nullptr;

    FVector ConveyorStart = FVector(-1.45, 0.0, 0.72);
    FVector ConveyorPickup = FVector(0.25, 0.0, 0.72);
    FVector RobotBase = FVector(0.25, 0.68, 0.72);
    FVector RobotHome = FVector(0.25, 0.33, 1.25);
    FVector ProductSize = FVector(0.08);
    FVector RedBin = FVector(0.90, 0.40, 0.72);
    FVector BlueBin = FVector(0.90, 1.00, 0.72);
    int64 LastSequence = -1;
    FString LastSession;
    FString LastConfiguration;

    void ReadConfiguration(const TSharedPtr<FJsonObject>& Configuration);
    void ApplySnapshot(const TSharedPtr<FJsonObject>& Snapshot);
    void UpdateArm(const FVector& Target, bool bGripperClosed);
    void UpdateProducts(const TSharedPtr<FJsonObject>& Snapshot);
    void Pose(UStaticMeshComponent* Component, const FVector& Position);
    void SetBeam(UStaticMeshComponent* Component, const FVector& Start, const FVector& End, double Width,
                 double Depth);
    void SetMaterial(UStaticMeshComponent* Component, FName Material);
};
