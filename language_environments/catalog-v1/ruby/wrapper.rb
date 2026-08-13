# frozen_string_literal: true

MASK = (1 << 64) - 1
GAMMA = 0x9e3779b97f4a7c15

class RpsRandom
  def initialize(seed)
    @state = seed & MASK
  end

  def next_uint64
    @state = (@state + GAMMA) & MASK
    value = @state
    value = ((value ^ (value >> 30)) * 0xbf58476d1ce4e5b9) & MASK
    value = ((value ^ (value >> 27)) * 0x94d049bb133111eb) & MASK
    (value ^ (value >> 31)) & MASK
  end

  def next_int(upper_exclusive)
    raise ArgumentError, "upper_exclusive must be positive" unless upper_exclusive.positive?
    threshold = ((-upper_exclusive) & MASK) % upper_exclusive
    loop do
      value = next_uint64
      return value % upper_exclusive if value >= threshold
    end
  end
end
RpsRandom.freeze

def fail_wrapper(message)
  warn "Ruby wrapper: #{message}"
  exit 2
end

if $PROGRAM_NAME == __FILE__
  fail_wrapper("unsupported RPS_PROTOCOL_VERSION") unless ENV["RPS_PROTOCOL_VERSION"] == "1"
  seed_text = ENV["RPS_SEED"]
  fail_wrapper("RPS_SEED must be an unsigned 64-bit integer") unless seed_text&.match?(/\A\d+\z/) && seed_text.to_i <= MASK
  rounds = ENV.fetch("RPS_ROUNDS", "")
  ENV.clear
  ENV.update("HOME" => "/tmp", "LANG" => "C.UTF-8", "LC_ALL" => "C.UTF-8", "TZ" => "UTC", "RPS_PROTOCOL_VERSION" => "1", "RPS_ROUNDS" => rounds, "RPS_SEED" => seed_text)
  original_stderr = STDERR.dup
  STDERR.reopen(File::NULL, "w")
  begin
    require_relative "strategy"
  ensure
    STDERR.reopen(original_stderr)
    original_stderr.close
  end
  rng = RpsRandom.new(seed_text.to_i)
  warn "RPS_READY_V1"
  STDERR.flush
  while (turn_text = STDIN.gets)
    my_history = STDIN.gets or break
    opponent_history = STDIN.gets or break
    turn = Integer(turn_text, exception: false)
    fail_wrapper("Turn must be a non-negative integer") unless turn&.>= 0
    move = choose_move(turn, my_history.strip == "-" ? "" : my_history.strip, opponent_history.strip == "-" ? "" : opponent_history.strip, rng)
    STDOUT.puts(move)
    STDOUT.flush
  end
end
