(ns rps-wrapper
  (:require [strategy]))

(definterface RpsRandomApi
  (^long nextLong [])
  (^long nextInt [^long upper-exclusive]))

(deftype RpsRandom [^:unsynchronized-mutable ^long state]
  RpsRandomApi
  (nextLong [_]
    (set! state (unchecked-add state -7046029254386353131))
    (let [mixed-1 (unchecked-multiply
                    (bit-xor state (unsigned-bit-shift-right state 30))
                    -4658895280553007687)
          mixed-2 (unchecked-multiply
                    (bit-xor mixed-1 (unsigned-bit-shift-right mixed-1 27))
                    -7723592293110705685)]
      (bit-xor mixed-2 (unsigned-bit-shift-right mixed-2 31))))
  (nextInt [this upper-exclusive]
    (when-not (pos? upper-exclusive)
      (throw (IllegalArgumentException. "upper-exclusive must be positive")))
    (let [threshold (Long/remainderUnsigned (- upper-exclusive) upper-exclusive)]
      (loop []
        (let [value (.nextLong this)]
          (if (not (neg? (Long/compareUnsigned value threshold)))
            (Long/remainderUnsigned value upper-exclusive)
            (recur)))))))

(defn- fail-wrapper [message]
  (binding [*out* *err*]
    (println (str "Clojure wrapper: " message))
    (flush))
  (System/exit 2))

(defn- parse-seed [value]
  (try
    (Long/parseUnsignedLong (or value ""))
    (catch NumberFormatException _
      (fail-wrapper "RPS_SEED must be an unsigned 64-bit integer"))))

(defn- history [value]
  (if (= value "-") "" value))

(defn -main [& _]
  (when-not (= "1" (System/getenv "RPS_PROTOCOL_VERSION"))
    (fail-wrapper "unsupported RPS_PROTOCOL_VERSION"))
  (let [rng (RpsRandom. (parse-seed (System/getenv "RPS_SEED")))
        input (java.io.BufferedReader. (java.io.InputStreamReader. System/in))]
    (binding [*out* *err*]
      (println "RPS_READY_V1")
      (flush))
    (loop []
      (when-let [turn-text (.readLine input)]
        (let [my-history (.readLine input)
              opponent-history (.readLine input)]
          (when (or (nil? my-history) (nil? opponent-history))
            (fail-wrapper "incomplete Turn request"))
          (let [turn (try
                       (Long/parseLong turn-text)
                       (catch NumberFormatException _
                         (fail-wrapper "Turn must be a non-negative integer")))]
            (when (neg? turn)
              (fail-wrapper "Turn must be a non-negative integer"))
            (let [move (strategy/choose-move
                         turn (history my-history) (history opponent-history) rng)]
              (println move)
              (flush)
              (recur))))))))
