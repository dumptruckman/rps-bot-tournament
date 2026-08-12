import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.SplittableRandom;
import java.util.TimeZone;

public final class RpsWrapper {
    private static final String READY_MARKER = "RPS_READY_V1";

    private RpsWrapper() {}

    private static String readHistory(String value) {
        return value.equals("-") ? "" : value;
    }

    private static void fail(String message) {
        System.err.println("Java wrapper: " + message);
        System.exit(2);
    }

    public static void main(String[] arguments) throws IOException {
        String seedValue = System.getenv("RPS_SEED");
        String protocolVersion = System.getenv("RPS_PROTOCOL_VERSION");
        if (!"1".equals(protocolVersion)) {
            fail("unsupported RPS_PROTOCOL_VERSION");
        }
        final long seed;
        try {
            seed = Long.parseUnsignedLong(seedValue);
        } catch (RuntimeException error) {
            fail("RPS_SEED must be an unsigned 64-bit integer");
            return;
        }
        Locale.setDefault(Locale.ROOT);
        TimeZone.setDefault(TimeZone.getTimeZone("UTC"));

        try {
            Class.forName("Strategy");
        } catch (ClassNotFoundException error) {
            fail("Strategy class is unavailable");
        }

        var rng = new SplittableRandom(seed);
        var input = new BufferedReader(
            new InputStreamReader(System.in, StandardCharsets.UTF_8)
        );
        var output = new BufferedWriter(
            new OutputStreamWriter(System.out, StandardCharsets.UTF_8)
        );
        System.err.println(READY_MARKER);
        System.err.flush();

        while (true) {
            String turnValue = input.readLine();
            if (turnValue == null) {
                return;
            }
            String myHistoryValue = input.readLine();
            String opponentHistoryValue = input.readLine();
            if (myHistoryValue == null || opponentHistoryValue == null) {
                return;
            }
            final int turn;
            try {
                turn = Integer.parseInt(turnValue.trim());
            } catch (NumberFormatException error) {
                fail("Turn must be an integer");
                return;
            }
            String move = Strategy.chooseMove(
                turn,
                readHistory(myHistoryValue),
                readHistory(opponentHistoryValue),
                rng
            );
            output.write(move == null ? "null" : move);
            output.newLine();
            output.flush();
        }
    }
}
