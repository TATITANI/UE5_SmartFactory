#pragma once

#include "Components/ActorComponent.h"
#include "CoreMinimal.h"
#include "IsaacBridgeComponent.generated.h"

class FJsonObject;
class FSocket;

/** 로컬 논블로킹 JSONL 통신입니다. Isaac이 공정 상태를 결정하고 Unreal이 표시합니다. */
UCLASS(ClassGroup = (SmartFactory), meta = (BlueprintSpawnableComponent))
class SMARTFACTORY_API UIsaacBridgeComponent : public UActorComponent
{
    GENERATED_BODY()

public:
    UIsaacBridgeComponent();

    /** 접속 주소는 IPv4 루프백으로 고정합니다. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Isaac Bridge",
              meta = (ClampMin = "1", ClampMax = "65535"))
    int32 Port = 9847;

    UPROPERTY(BlueprintReadOnly, Category = "Isaac Bridge")
    bool bConnected = false;

    UPROPERTY(BlueprintReadOnly, Category = "Isaac Bridge")
    bool bHasFreshState = false;

    UPROPERTY(BlueprintReadOnly, Category = "Isaac Bridge")
    FString Mode = TEXT("disconnected");

    UPROPERTY(BlueprintReadOnly, Category = "Isaac Bridge")
    FString Phase = TEXT("waiting");

    UPROPERTY(BlueprintReadOnly, Category = "Isaac Bridge")
    FString LastCommandStatus = TEXT("Waiting for Isaac Sim");

    UPROPERTY(BlueprintReadOnly, Category = "Isaac Bridge")
    FString LastCommandId;

    UPROPERTY(BlueprintReadOnly, Category = "Isaac Bridge")
    FString LastAcknowledgedCommandId;

    UPROPERTY(BlueprintReadOnly, Category = "Isaac Bridge")
    bool bLastCommandAccepted = false;

    UPROPERTY(BlueprintReadOnly, Category = "Isaac Bridge")
    int32 SortedCount = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Isaac Bridge")
    int32 RedCount = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Isaac Bridge")
    int32 BlueCount = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Isaac Bridge")
    double SimulationTime = 0.0;

    /** 일시정지 중에도 유지하는 컨베이어 설정 속도입니다. 단위는 m/s입니다. */
    UPROPERTY(BlueprintReadOnly, Category = "Isaac Bridge")
    double ConveyorSpeedSetpoint = 0.35;

    /** 현재 벨트의 유효 속도이며 정지 중에는 0입니다. */
    UPROPERTY(BlueprintReadOnly, Category = "Isaac Bridge")
    double EffectiveConveyorSpeed = 0.0;

    UPROPERTY(BlueprintReadOnly, Category = "Isaac Bridge")
    int64 SnapshotSequence = -1;

    UPROPERTY(BlueprintReadOnly, Category = "Isaac Bridge")
    FString SessionId;

    /** true는 현재 연결의 전송 대기열 등록 성공이며 명령 수락 여부는 응답으로 확인합니다. */
    UFUNCTION(BlueprintCallable, Category = "Isaac Bridge")
    bool SendCommand(const FString& Command);

    /** 0.05~1.0 m/s 범위의 유한한 속도 명령을 등록합니다. */
    UFUNCTION(BlueprintCallable, Category = "Isaac Bridge")
    bool SendConveyorSpeed(double Speed);

    UFUNCTION(BlueprintPure, Category = "Isaac Bridge")
    double GetStateAgeSeconds() const;

    const TSharedPtr<FJsonObject>& GetSnapshot() const
    {
        return Snapshot;
    }
    const TSharedPtr<FJsonObject>& GetConfiguration() const
    {
        return Configuration;
    }

    virtual void TickComponent(float DeltaTime, ELevelTick TickType,
                               FActorComponentTickFunction* ThisTickFunction) override;

protected:
    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
    virtual void BeginDestroy() override;

private:
    friend class FIsaacBridgeProtocolTest;

    struct FPendingCommand
    {
        FString Command;
        double QueuedAt = 0.0;
        TOptional<double> Value;
    };

    void StartConnection(double Now);
    void Disconnect(const FString& Reason, double Now);
    void ReleaseSocket();
    void ReceiveFrames(double Now);
    void FlushCommands(double Now);
    bool ProcessFrame(const FString& Line, double Now);
    bool QueueCommand(const FString& Command, const TOptional<double>& Value);
    static bool EncodeCommand(const FString& Command, const TOptional<double>& Value, FString& OutId,
                              FString& OutLine);

    FSocket* Socket = nullptr;
    bool bConnecting = false;
    double ConnectStartedAt = 0.0;
    double NextConnectAt = 0.0;
    double ReconnectDelay = 0.5;
    double LastSnapshotAt = -1.0;
    TArray<uint8> ReceiveBuffer;
    TArray<uint8> SendBuffer;
    int32 SendOffset = 0;
    TMap<FString, FPendingCommand> PendingCommands;
    TSharedPtr<FJsonObject> Snapshot;
    TSharedPtr<FJsonObject> Configuration;
};
