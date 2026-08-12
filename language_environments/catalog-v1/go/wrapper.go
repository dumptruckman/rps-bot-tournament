package main

import (
	"bufio"
	"fmt"
	rand "math/rand/v2"
	"os"
	"strconv"
	"strings"
)

const readyMarker = "RPS_READY_V1"
const seedDomain = uint64(0x9e3779b97f4a7c15)

func readHistory(value string) string {
	if value == "-" {
		return ""
	}
	return value
}

func fail(message string) {
	fmt.Fprintln(os.Stderr, "Go wrapper:", message)
	os.Exit(2)
}

func main() {
	seedValue := os.Getenv("RPS_SEED")
	protocolVersion := os.Getenv("RPS_PROTOCOL_VERSION")
	rounds := os.Getenv("RPS_ROUNDS")
	seed, err := strconv.ParseUint(seedValue, 10, 64)
	if err != nil {
		fail("RPS_SEED must be an unsigned 64-bit integer")
	}
	if protocolVersion != "1" {
		fail("unsupported RPS_PROTOCOL_VERSION")
	}
	os.Clearenv()
	for name, value := range map[string]string{
		"HOME": "/tmp", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC",
		"RPS_PROTOCOL_VERSION": protocolVersion, "RPS_ROUNDS": rounds, "RPS_SEED": seedValue,
	} {
		if err := os.Setenv(name, value); err != nil {
			fail("could not sanitize process environment")
		}
	}

	rng := rand.New(rand.NewPCG(seed, seed^seedDomain))
	input := bufio.NewScanner(os.Stdin)
	output := bufio.NewWriter(os.Stdout)
	fmt.Fprintln(os.Stderr, readyMarker)
	for input.Scan() {
		turnValue := input.Text()
		if !input.Scan() {
			return
		}
		myHistory := readHistory(input.Text())
		if !input.Scan() {
			return
		}
		opponentHistory := readHistory(input.Text())
		turn, err := strconv.Atoi(strings.TrimSpace(turnValue))
		if err != nil {
			fail("Turn must be an integer")
		}
		fmt.Fprintln(output, ChooseMove(turn, myHistory, opponentHistory, rng))
		if err := output.Flush(); err != nil {
			return
		}
	}
	if err := input.Err(); err != nil {
		fail("protocol input failed")
	}
}
