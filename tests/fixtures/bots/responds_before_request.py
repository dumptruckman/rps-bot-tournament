import sys
import time


responses = sys.argv[1]
delay_between_responses_seconds = float(sys.argv[2])

for _ in range(3):
    sys.stdin.readline()
print(responses[0], flush=True)
for response in responses[1:]:
    time.sleep(delay_between_responses_seconds)
    print(response, flush=True)
while True:
    time.sleep(1)
