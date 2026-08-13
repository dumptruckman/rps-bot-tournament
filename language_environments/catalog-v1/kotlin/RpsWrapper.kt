import java.io.BufferedReader
import java.io.BufferedWriter
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.nio.charset.StandardCharsets
import java.util.Locale
import java.util.SplittableRandom
import java.util.TimeZone

object RpsWrapper {
    private const val READY_MARKER = "RPS_READY_V1"

    private fun readHistory(value: String): String = if (value == "-") "" else value

    private fun fail(message: String): Nothing {
        System.err.println("Kotlin wrapper: $message")
        kotlin.system.exitProcess(2)
    }

    @JvmStatic
    fun main(arguments: Array<String>) {
        val protocolVersion = System.getenv("RPS_PROTOCOL_VERSION")
        if (protocolVersion != "1") fail("unsupported RPS_PROTOCOL_VERSION")
        val seed = try {
            java.lang.Long.parseUnsignedLong(System.getenv("RPS_SEED"))
        } catch (_: RuntimeException) {
            fail("RPS_SEED must be an unsigned 64-bit integer")
        }

        Locale.setDefault(Locale.ROOT)
        TimeZone.setDefault(TimeZone.getTimeZone("UTC"))
        val rng = SplittableRandom(seed)
        val input = BufferedReader(InputStreamReader(System.`in`, StandardCharsets.UTF_8))
        val output = BufferedWriter(OutputStreamWriter(System.out, StandardCharsets.UTF_8))
        System.err.println(READY_MARKER)
        System.err.flush()

        while (true) {
            val turnValue = input.readLine() ?: return
            val myHistoryValue = input.readLine() ?: return
            val opponentHistoryValue = input.readLine() ?: return
            val turn = turnValue.trim().toIntOrNull() ?: fail("Turn must be an integer")
            val move = Strategy.chooseMove(
                turn,
                readHistory(myHistoryValue),
                readHistory(opponentHistoryValue),
                rng,
            )
            output.write(move)
            output.newLine()
            output.flush()
        }
    }
}
