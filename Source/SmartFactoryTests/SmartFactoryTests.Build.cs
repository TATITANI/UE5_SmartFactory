using UnrealBuildTool;

public class SmartFactoryTests : ModuleRules
{
    public SmartFactoryTests(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PrivateDependencyModuleNames.AddRange(new[]
        {
            "Core",
            "CoreUObject",
            "Engine",
            "Json",
            "SmartFactory"
        });
    }
}
