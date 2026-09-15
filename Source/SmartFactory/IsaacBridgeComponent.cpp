#include "IsaacBridgeComponent.h"

#include "Containers/StringConv.h"
#include "Dom/JsonObject.h"
#include "HAL/PlatformTime.h"
#include "IPAddress.h"
#include "Misc/Guid.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "SocketSubsystem.h"
#include "Sockets.h"

DEFINE_LOG_CATEGORY_STATIC(LogIsaacBridge, Log, All);

namespace IsaacBridge
{
constexpr int32 MaxFrameBytes = 64 * 1024;
constexpr double StaleSeconds = 2.0;
constexpr double CommandTimeoutSeconds = 3.0;
constexpr double MaxExactInteger = 9007199254740991.0;

bool Number(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key, double& Out)
{
    return Object.IsValid() && Object->HasTypedField<EJson::Number>(Key) &&
           Object->TryGetNumberField(Key, Out) && FMath::IsFinite(Out);
}

bool Integer(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key, double& Out,
             double Max = MaxExactInteger)
{
    return Number(Object, Key, Out) && Out >= 0.0 && Out <= Max && FMath::FloorToDouble(Out) == Out;
}

bool String(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key, FString& Out, int32 Max = 128)
{
    return Object.IsValid() && Object->HasTypedField<EJson::String>(Key) &&
           Object->TryGetStringField(Key, Out) && !Out.IsEmpty() && Out.Len() <= Max;
}

bool Boolean(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key, bool& Out)
{
    return Object.IsValid() && Object->HasTypedField<EJson::Boolean>(Key) &&
           Object->TryGetBoolField(Key, Out);
}

bool ObjectField(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key, TSharedPtr<FJsonObject>& Out)
{
    const TSharedPtr<FJsonObject>* Found = nullptr;
    if (!Object.IsValid() || !Object->TryGetObjectField(Key, Found) || !Found || !Found->IsValid())
    {
        return false;
    }
    Out = *Found;
    return true;
}

bool VectorField(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key)
{
    const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
    if (!Object->TryGetArrayField(Key, Values) || !Values || Values->Num() != 3)
    {
        return false;
    }
    for (const TSharedPtr<FJsonValue>& Value : *Values)
    {
        double Coordinate = 0.0;
        if (!Value.IsValid() || Value->Type != EJson::Number || !Value->TryGetNumber(Coordinate) ||
            !FMath::IsFinite(Coordinate) || FMath::Abs(Coordinate) > 10000.0)
        {
            return false;
        }
    }
    return true;
}

bool Product(const TSharedPtr<FJsonValue>& Value)
{
    const TSharedPtr<FJsonObject>* Found = nullptr;
    if (!Value.IsValid() || !Value->TryGetObject(Found) || !Found || !Found->IsValid())
    {
        return false;
    }
    const TSharedPtr<FJsonObject>& Object = *Found;
    FString Id, Color;
    double NumericId = 0.0;
    bool Attached = false;
    return (String(Object, TEXT("id"), Id) || Integer(Object, TEXT("id"), NumericId)) &&
           String(Object, TEXT("color"), Color) && (Color == TEXT("red") || Color == TEXT("blue")) &&
           VectorField(Object, TEXT("position")) && Boolean(Object, TEXT("attached"), Attached);
}

bool JointState(const TSharedPtr<FJsonObject>& Snapshot)
{
    // 코어 전용 통합 검사에서는 Isaac 로봇 어댑터를 생성하지 않습니다.
    if (!Snapshot->HasField(TEXT("robot_joint_state")))
    {
        return true;
    }
    TSharedPtr<FJsonObject> Joints;
    const TArray<TSharedPtr<FJsonValue>>* Names = nullptr;
    const TArray<TSharedPtr<FJsonValue>>* Positions = nullptr;
    double Error = 0.0;
    bool Reachable = false;
    if (!ObjectField(Snapshot, TEXT("robot_joint_state"), Joints) ||
        !Joints->TryGetArrayField(TEXT("names"), Names) || !Names ||
        !Joints->TryGetArrayField(TEXT("positions"), Positions) || !Positions ||
        Names->Num() != Positions->Num() || Names->Num() > 32 ||
        !Number(Joints, TEXT("reach_error"), Error) || Error < 0.0 ||
        !Boolean(Joints, TEXT("reachable"), Reachable))
    {
        return false;
    }
    for (int32 Index = 0; Index < Names->Num(); ++Index)
    {
        FString Name;
        double Angle = 0.0;
        if (!(*Names)[Index].IsValid() || (*Names)[Index]->Type != EJson::String ||
            !(*Names)[Index]->TryGetString(Name) || Name.IsEmpty() || Name.Len() > 128 ||
            !(*Positions)[Index].IsValid() || (*Positions)[Index]->Type != EJson::Number ||
            !(*Positions)[Index]->TryGetNumber(Angle) || !FMath::IsFinite(Angle) ||
            FMath::Abs(Angle) > 10000.0)
        {
            return false;
        }
    }
    return true;
}

bool IsMode(const FString& Mode)
{
    return Mode == TEXT("running") || Mode == TEXT("paused") || Mode == TEXT("emergency_stopped") ||
           Mode == TEXT("bin_full");
}

bool IsPhase(const FString& Phase)
{
    return Phase == TEXT("conveying") || Phase == TEXT("approaching") || Phase == TEXT("picking") ||
           Phase == TEXT("lifting") || Phase == TEXT("transferring") || Phase == TEXT("placing") ||
           Phase == TEXT("releasing") || Phase == TEXT("retracting");
}

bool IsCommand(const FString& Command)
{
    return Command == TEXT("resume") || Command == TEXT("pause") || Command == TEXT("emergency_stop") ||
           Command == TEXT("reset") || Command == TEXT("set_conveyor_speed");
}

bool IsSpeed(double Speed)
{
    return FMath::IsFinite(Speed) && Speed >= 0.05 && Speed <= 1.0;
}

bool ConveyorSpeeds(const TSharedPtr<FJsonObject>& Snapshot, const TSharedPtr<FJsonObject>& Config,
                    double& OutSetpoint, double& OutEffective)
{
    // 이전 프로토콜 1은 config.conveyor.speed만 제공합니다.
    // 초기 검사 데이터에는 컨베이어 설정이 없어 기본값을 유지합니다.
    OutSetpoint = 0.35;
    OutEffective = 0.0;
    if (Snapshot->HasField(TEXT("conveyor_speed_setpoint")))
    {
        if (!Number(Snapshot, TEXT("conveyor_speed_setpoint"), OutSetpoint) || !IsSpeed(OutSetpoint))
        {
            return false;
        }
    }
    else if (Config->HasField(TEXT("conveyor")))
    {
        TSharedPtr<FJsonObject> Conveyor;
        if (!ObjectField(Config, TEXT("conveyor"), Conveyor))
        {
            return false;
        }
        if (Conveyor->HasField(TEXT("speed")) &&
            (!Number(Conveyor, TEXT("speed"), OutSetpoint) || !IsSpeed(OutSetpoint)))
        {
            return false;
        }
    }
    return !Snapshot->HasField(TEXT("conveyor_speed")) ||
           (Number(Snapshot, TEXT("conveyor_speed"), OutEffective) && OutEffective >= 0.0 &&
            OutEffective <= 1.0);
}
} // namespace IsaacBridge

UIsaacBridgeComponent::UIsaacBridgeComponent()
{
    PrimaryComponentTick.bCanEverTick = true;
    PrimaryComponentTick.bStartWithTickEnabled = true;
    PrimaryComponentTick.TickGroup = TG_PrePhysics;
    bAutoActivate = true;
}

void UIsaacBridgeComponent::BeginPlay()
{
    Super::BeginPlay();
    NextConnectAt = FPlatformTime::Seconds();
}

void UIsaacBridgeComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    Disconnect(TEXT("Unreal play session ended"), FPlatformTime::Seconds());
    Super::EndPlay(EndPlayReason);
}

void UIsaacBridgeComponent::BeginDestroy()
{
    ReleaseSocket();
    Super::BeginDestroy();
}

double UIsaacBridgeComponent::GetStateAgeSeconds() const
{
    return LastSnapshotAt < 0.0 ? -1.0 : FMath::Max(0.0, FPlatformTime::Seconds() - LastSnapshotAt);
}

void UIsaacBridgeComponent::ReleaseSocket()
{
    if (Socket)
    {
        Socket->Close();
        if (ISocketSubsystem* Subsystem = ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM))
        {
            Subsystem->DestroySocket(Socket);
        }
        Socket = nullptr;
    }
}

void UIsaacBridgeComponent::Disconnect(const FString& Reason, double Now)
{
    ReleaseSocket();
    bConnected = bHasFreshState = bConnecting = false;
    ReceiveBuffer.Reset();
    SendBuffer.Reset();
    SendOffset = 0;
    // 일부만 전송되었거나 응답 없는 명령은 처리 여부가 불명확하므로 재전송하지 않습니다.
    LastCommandStatus = PendingCommands.IsEmpty()
                            ? Reason
                            : TEXT("Disconnected; pending command outcome unknown (not replayed)");
    PendingCommands.Reset();
    NextConnectAt = Now + ReconnectDelay;
    ReconnectDelay = FMath::Min(4.0, ReconnectDelay * 2.0);
    UE_LOG(LogIsaacBridge, Verbose, TEXT("%s; reconnect in %.1fs"), *Reason, NextConnectAt - Now);
}

void UIsaacBridgeComponent::StartConnection(double Now)
{
    ISocketSubsystem* Subsystem = ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM);
    if (!Subsystem || Port < 1 || Port > 65535)
    {
        Disconnect(TEXT("Invalid bridge port or socket subsystem unavailable"), Now);
        return;
    }
    Socket =
        Subsystem->CreateSocket(NAME_Stream, TEXT("Isaac local factory bridge"), FNetworkProtocolTypes::IPv4);
    if (!Socket || !Socket->SetNonBlocking(true))
    {
        Disconnect(TEXT("Cannot create bridge socket"), Now);
        return;
    }
    Socket->SetNoDelay(true);
    TSharedRef<FInternetAddr> Address = Subsystem->CreateInternetAddr();
    bool bValidAddress = false;
    Address->SetIp(TEXT("127.0.0.1"), bValidAddress);
    Address->SetPort(Port);
    if (!bValidAddress || !Socket->Connect(*Address))
    {
        Disconnect(TEXT("Waiting for Isaac Sim bridge"), Now);
        return;
    }
    bConnecting = true;
    ConnectStartedAt = Now;
}

void UIsaacBridgeComponent::TickComponent(float DeltaTime, ELevelTick TickType,
                                          FActorComponentTickFunction* ThisTickFunction)
{
    Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
    const double Now = FPlatformTime::Seconds();
    if (!Socket)
    {
        if (Now >= NextConnectAt)
        {
            StartConnection(Now);
        }
        return;
    }
    if (bConnecting)
    {
        if (Socket->Wait(ESocketWaitConditions::WaitForWrite, FTimespan::Zero()))
        {
            ISocketSubsystem* Subsystem = ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM);
            TSharedRef<FInternetAddr> Peer = Subsystem->CreateInternetAddr();
            if (!Socket->GetPeerAddress(*Peer))
            {
                Disconnect(TEXT("Isaac connection failed"), Now);
                return;
            }
            bConnecting = false;
            bConnected = true;
            LastCommandStatus = TEXT("Connected; waiting for fresh state");
            UE_LOG(LogIsaacBridge, Log, TEXT("Connected to Isaac Sim at 127.0.0.1:%d"), Port);
        }
        else if (Now - ConnectStartedAt > 3.0)
        {
            Disconnect(TEXT("Isaac connection timed out"), Now);
            return;
        }
    }
    if (!bConnected)
    {
        return;
    }
    ReceiveFrames(Now);
    if (!Socket)
    {
        return;
    }
    bHasFreshState = Snapshot.IsValid() && LastSnapshotAt >= ConnectStartedAt &&
                     Now - LastSnapshotAt <= IsaacBridge::StaleSeconds;
    if ((!bHasFreshState && Now - ConnectStartedAt > IsaacBridge::StaleSeconds) ||
        (LastSnapshotAt >= ConnectStartedAt && Now - LastSnapshotAt > IsaacBridge::StaleSeconds))
    {
        Disconnect(TEXT("State stale; reconnecting to Isaac Sim"), Now);
        return;
    }
    for (auto It = PendingCommands.CreateIterator(); It; ++It)
    {
        if (Now - It.Value().QueuedAt > IsaacBridge::CommandTimeoutSeconds)
        {
            // 응답 대기 시간이 지나면 연결을 닫고 미전송 바이트도 버립니다.
            Disconnect(TEXT("Command acknowledgement timed out; outcome unknown"), Now);
            return;
        }
    }
    FlushCommands(Now);
}

void UIsaacBridgeComponent::ReceiveFrames(double Now)
{
    uint8 Bytes[8192];
    // 다른 로컬 프로세스가 데이터를 과도하게 보내도 프레임당 작업량을 제한합니다.
    for (int32 Batch = 0; Batch < 16 && Socket; ++Batch)
    {
        int32 Read = 0;
        if (!Socket->Recv(Bytes, UE_ARRAY_COUNT(Bytes), Read, ESocketReceiveFlags::None))
        {
            Disconnect(TEXT("Isaac Sim disconnected"), Now);
            return;
        }
        if (Read <= 0)
        {
            break;
        }
        ReceiveBuffer.Append(Bytes, Read);
        int32 Newline = INDEX_NONE;
        while (ReceiveBuffer.Find(static_cast<uint8>('\n'), Newline))
        {
            if (Newline + 1 > IsaacBridge::MaxFrameBytes)
            {
                Disconnect(TEXT("Isaac frame exceeded 64 KiB"), Now);
                return;
            }
            FUTF8ToTCHAR Converted(reinterpret_cast<const ANSICHAR*>(ReceiveBuffer.GetData()), Newline);
            const FString Line(Converted.Length(), Converted.Get());
            ReceiveBuffer.RemoveAt(0, Newline + 1, EAllowShrinking::No);
            if (!ProcessFrame(Line, Now))
            {
                Disconnect(TEXT("Rejected invalid Isaac bridge message"), Now);
                return;
            }
        }
        if (ReceiveBuffer.Num() >= IsaacBridge::MaxFrameBytes)
        {
            Disconnect(TEXT("Isaac frame exceeded 64 KiB"), Now);
            return;
        }
    }
}

bool UIsaacBridgeComponent::ProcessFrame(const FString& Line, double Now)
{
    using namespace IsaacBridge;
    TSharedPtr<FJsonObject> Message;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Line);
    FString Type;
    double Protocol = 0.0;
    if (!FJsonSerializer::Deserialize(Reader, Message) || !Message.IsValid() ||
        !Integer(Message, TEXT("protocol"), Protocol) || Protocol != 1.0 ||
        !String(Message, TEXT("type"), Type))
    {
        return false;
    }
    if (Type == TEXT("ack"))
    {
        FString Id, Command, AckMode, Reason;
        bool Accepted = false;
        if (!String(Message, TEXT("id"), Id) || !String(Message, TEXT("command"), Command) ||
            !IsCommand(Command) || !String(Message, TEXT("mode"), AckMode) || !IsMode(AckMode) ||
            !Boolean(Message, TEXT("accepted"), Accepted) ||
            !Message->HasTypedField<EJson::String>(TEXT("reason")) ||
            !Message->TryGetStringField(TEXT("reason"), Reason) || Reason.Len() > 512)
        {
            return false;
        }
        double AckValue = 0.0;
        const bool bHasAckValue = Message->HasField(TEXT("value"));
        if (bHasAckValue && (Command != TEXT("set_conveyor_speed") ||
                             !Number(Message, TEXT("value"), AckValue) || !IsSpeed(AckValue)))
        {
            return false;
        }
        const FPendingCommand* Pending = PendingCommands.Find(Id);
        if (Pending && Pending->Command == Command)
        {
            if (bHasAckValue && (!Pending->Value.IsSet() ||
                                 !FMath::IsNearlyEqual(AckValue, Pending->Value.GetValue(), 1.e-12)))
            {
                return false;
            }
            PendingCommands.Remove(Id);
            LastAcknowledgedCommandId = Id;
            if (Id == LastCommandId)
            {
                bLastCommandAccepted = Accepted;
                LastCommandStatus = FString::Printf(TEXT("%s: %s%s%s"), *Command,
                                                    Accepted ? TEXT("accepted") : TEXT("rejected"),
                                                    Reason.IsEmpty() ? TEXT("") : TEXT(" - "), *Reason);
            }
            UE_LOG(LogIsaacBridge, Log, TEXT("Command ack %s: %s (%s)"), *Command,
                   Accepted ? TEXT("accepted") : TEXT("rejected"), *Reason);
        }
        return true;
    }
    if (Type != TEXT("snapshot"))
    {
        return false;
    }

    FString NewSession, NewMode, NewPhase;
    double Sequence = 0.0, Time = 0.0, Placed = 0.0, Red = 0.0, Blue = 0.0;
    double NewSpeedSetpoint = 0.35, NewEffectiveSpeed = 0.0;
    TSharedPtr<FJsonObject> NewSnapshot, NewConfig, Robot, Counters, Colors;
    const TArray<TSharedPtr<FJsonValue>>* Products = nullptr;
    bool Flag = false;
    if (!String(Message, TEXT("session_id"), NewSession) || !Integer(Message, TEXT("sequence"), Sequence) ||
        !ObjectField(Message, TEXT("snapshot"), NewSnapshot) ||
        !ObjectField(Message, TEXT("config"), NewConfig) ||
        !Number(NewSnapshot, TEXT("simulation_time"), Time) || Time < 0.0 || Time > MaxExactInteger ||
        !String(NewSnapshot, TEXT("mode"), NewMode) || !IsMode(NewMode) ||
        !String(NewSnapshot, TEXT("state"), NewPhase) || !IsPhase(NewPhase) ||
        !Boolean(NewSnapshot, TEXT("conveyor_running"), Flag) ||
        !Boolean(NewSnapshot, TEXT("pickup_sensor"), Flag) ||
        !ObjectField(NewSnapshot, TEXT("robot_target"), Robot) || !VectorField(Robot, TEXT("position")) ||
        !Boolean(Robot, TEXT("gripper_closed"), Flag) ||
        !ObjectField(NewSnapshot, TEXT("counters"), Counters) ||
        !Integer(Counters, TEXT("placed"), Placed, MAX_int32) ||
        !ObjectField(Counters, TEXT("by_color"), Colors) || !Integer(Colors, TEXT("red"), Red, MAX_int32) ||
        !Integer(Colors, TEXT("blue"), Blue, MAX_int32) || Red + Blue != Placed ||
        !NewSnapshot->TryGetArrayField(TEXT("placed_products"), Products) || !Products ||
        Products->Num() > 512 || !JointState(NewSnapshot))
    {
        return false;
    }
    if (!ConveyorSpeeds(NewSnapshot, NewConfig, NewSpeedSetpoint, NewEffectiveSpeed))
    {
        return false;
    }
    const TSharedPtr<FJsonValue> Active = NewSnapshot->TryGetField(TEXT("active_product"));
    if (!Active.IsValid() || (!Active->IsNull() && !Product(Active)))
    {
        return false;
    }
    for (const TSharedPtr<FJsonValue>& Item : *Products)
    {
        if (!Product(Item))
        {
            return false;
        }
    }
    if (SessionId == NewSession && static_cast<int64>(Sequence) <= SnapshotSequence)
    {
        // 중복되거나 순서가 뒤바뀐 상태로 최신 수신 시각을 갱신하지 않습니다.
        return true;
    }
    if (!SessionId.IsEmpty() && SessionId != NewSession)
    {
        // 서버 세션이 바뀌면 이전 세션의 명령 응답을 무효화합니다.
        SendBuffer.Reset();
        SendOffset = 0;
        PendingCommands.Reset();
        LastCommandId.Reset();
        LastAcknowledgedCommandId.Reset();
        bLastCommandAccepted = false;
    }
    const bool bFirstFresh = !bHasFreshState;
    Snapshot = MoveTemp(NewSnapshot);
    Configuration = MoveTemp(NewConfig);
    SessionId = MoveTemp(NewSession);
    SnapshotSequence = static_cast<int64>(Sequence);
    Mode = MoveTemp(NewMode);
    Phase = MoveTemp(NewPhase);
    SimulationTime = Time;
    ConveyorSpeedSetpoint = NewSpeedSetpoint;
    EffectiveConveyorSpeed = NewEffectiveSpeed;
    SortedCount = static_cast<int32>(Placed);
    RedCount = static_cast<int32>(Red);
    BlueCount = static_cast<int32>(Blue);
    LastSnapshotAt = Now;
    bHasFreshState = bConnected;
    ReconnectDelay = 0.5;
    if (bFirstFresh && PendingCommands.IsEmpty())
    {
        LastCommandStatus = TEXT("Live state received; controls ready");
        UE_LOG(LogIsaacBridge, Log, TEXT("Live Isaac state session=%s sequence=%lld mode=%s"), *SessionId,
               SnapshotSequence, *Mode);
    }
    return true;
}

bool UIsaacBridgeComponent::SendCommand(const FString& Command)
{
    return QueueCommand(Command, TOptional<double>());
}

bool UIsaacBridgeComponent::SendConveyorSpeed(double Speed)
{
    return QueueCommand(TEXT("set_conveyor_speed"), TOptional<double>(Speed));
}

bool UIsaacBridgeComponent::EncodeCommand(const FString& Command, const TOptional<double>& Value,
                                          FString& OutId, FString& OutLine)
{
    OutId.Reset();
    OutLine.Reset();
    const bool bSpeedCommand = Command == TEXT("set_conveyor_speed");
    if (!IsaacBridge::IsCommand(Command) || bSpeedCommand != Value.IsSet() ||
        (Value.IsSet() && !IsaacBridge::IsSpeed(Value.GetValue())))
    {
        return false;
    }
    OutId = FGuid::NewGuid().ToString(EGuidFormats::DigitsWithHyphensLower);
    TSharedRef<FJsonObject> Message = MakeShared<FJsonObject>();
    Message->SetStringField(TEXT("type"), TEXT("command"));
    Message->SetNumberField(TEXT("protocol"), 1);
    Message->SetStringField(TEXT("id"), OutId);
    Message->SetStringField(TEXT("command"), Command);
    if (Value.IsSet())
    {
        Message->SetNumberField(TEXT("value"), Value.GetValue());
    }
    const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
        TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&OutLine);
    if (!FJsonSerializer::Serialize(Message, Writer))
    {
        OutId.Reset();
        OutLine.Reset();
        return false;
    }
    OutLine += TEXT("\n");
    return true;
}

bool UIsaacBridgeComponent::QueueCommand(const FString& Command, const TOptional<double>& Value)
{
    FString Id, Line;
    if (!EncodeCommand(Command, Value, Id, Line))
    {
        LastCommandStatus = Command == TEXT("set_conveyor_speed")
                                ? TEXT("Speed must be a finite value from 0.05 to 1.0 m/s")
                                : TEXT("Unsupported command");
        return false;
    }
    const double Now = FPlatformTime::Seconds();
    if (!Socket || !bConnected || !bHasFreshState || LastSnapshotAt < ConnectStartedAt ||
        Now - LastSnapshotAt > IsaacBridge::StaleSeconds)
    {
        LastCommandStatus = TEXT("Command blocked: waiting for fresh Isaac state");
        return false;
    }
    if (PendingCommands.Num() >= 16 || SendBuffer.Num() - SendOffset > 8192)
    {
        LastCommandStatus = TEXT("Command queue full; wait for acknowledgement");
        return false;
    }
    FTCHARToUTF8 Encoded(*Line);
    // 부분 프레임을 보존하면서 이미 전송한 접두 데이터를 정리합니다.
    if (SendOffset > 0)
    {
        SendBuffer.RemoveAt(0, SendOffset, EAllowShrinking::No);
        SendOffset = 0;
    }
    SendBuffer.Append(reinterpret_cast<const uint8*>(Encoded.Get()), Encoded.Length());
    PendingCommands.Add(Id, FPendingCommand{Command, Now, Value});
    LastCommandId = Id;
    bLastCommandAccepted = false;
    LastCommandStatus = Command + TEXT(": awaiting acknowledgement");
    FlushCommands(Now);
    return Socket != nullptr;
}

void UIsaacBridgeComponent::FlushCommands(double Now)
{
    if (!Socket || SendOffset >= SendBuffer.Num())
    {
        return;
    }
    int32 Sent = 0;
    if (!Socket->Send(SendBuffer.GetData() + SendOffset, SendBuffer.Num() - SendOffset, Sent))
    {
        ISocketSubsystem* Subsystem = ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM);
        if (!Subsystem || Subsystem->GetLastErrorCode() != SE_EWOULDBLOCK)
        {
            Disconnect(TEXT("Isaac command transport failed"), Now);
        }
        return;
    }
    SendOffset += FMath::Max(0, Sent);
    if (SendOffset == SendBuffer.Num())
    {
        SendBuffer.Reset();
        SendOffset = 0;
    }
}
