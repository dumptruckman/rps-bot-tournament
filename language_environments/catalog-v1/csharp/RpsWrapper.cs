using System;
using System.Globalization;
using System.Runtime.CompilerServices;

public sealed class RpsRandom
{
    private const ulong Gamma = 0x9e3779b97f4a7c15UL;
    private ulong state;

    public RpsRandom(ulong seed) => state = seed;

    public ulong NextUInt64()
    {
        state = unchecked(state + Gamma);
        ulong value = state;
        value = unchecked((value ^ (value >> 30)) * 0xbf58476d1ce4e5b9UL);
        value = unchecked((value ^ (value >> 27)) * 0x94d049bb133111ebUL);
        return value ^ (value >> 31);
    }

    public int NextInt(int upperExclusive)
    {
        if (upperExclusive <= 0)
            throw new ArgumentOutOfRangeException(nameof(upperExclusive));
        ulong bound = (ulong)upperExclusive;
        ulong threshold = unchecked(0UL - bound) % bound;
        ulong value;
        do value = NextUInt64(); while (value < threshold);
        return (int)(value % bound);
    }
}

public static class RpsWrapper
{
    private static void Fail(string message)
    {
        Console.Error.WriteLine("C# wrapper: " + message);
        Environment.Exit(2);
    }

    public static void Main()
    {
        if (Environment.GetEnvironmentVariable("RPS_PROTOCOL_VERSION") != "1")
            Fail("unsupported RPS_PROTOCOL_VERSION");
        if (!ulong.TryParse(
                Environment.GetEnvironmentVariable("RPS_SEED"),
                NumberStyles.None,
                CultureInfo.InvariantCulture,
                out ulong seed))
            Fail("RPS_SEED must be an unsigned 64-bit integer");

        CultureInfo.DefaultThreadCurrentCulture = CultureInfo.InvariantCulture;
        CultureInfo.DefaultThreadCurrentUICulture = CultureInfo.InvariantCulture;
        var rng = new RpsRandom(seed);
        RuntimeHelpers.RunClassConstructor(typeof(Strategy).TypeHandle);
        Console.Error.WriteLine("RPS_READY_V1");
        Console.Error.Flush();

        while (true)
        {
            string? turnValue = Console.ReadLine();
            if (turnValue is null) return;
            string? myHistory = Console.ReadLine();
            string? opponentHistory = Console.ReadLine();
            if (myHistory is null || opponentHistory is null) return;
            if (!int.TryParse(turnValue, NumberStyles.Integer, CultureInfo.InvariantCulture, out int turn))
                Fail("Turn must be an integer");
            string move = Strategy.ChooseMove(
                turn,
                myHistory == "-" ? "" : myHistory,
                opponentHistory == "-" ? "" : opponentHistory,
                rng);
            Console.WriteLine(move ?? "null");
            Console.Out.Flush();
        }
    }
}
