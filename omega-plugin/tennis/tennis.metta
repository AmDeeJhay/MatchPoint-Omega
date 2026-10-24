;; =====================================================================
;; World Tennis match coordinator - Omega plugin (Track 04)
;; AI Omega Lisbon Developer Buildathon
;;
;; MeTTa rules decide WHO plays WHOM, WHERE and WHEN:
;;   level fit      - |level difference| must be <= 0.5
;;   travel         - each player's trip to the court <= their own max km
;;   availability   - both players free + court open + slot not blocked
;; The LLM in Omega's loop calls the skills below; it never invents a
;; match itself. Booking is SIMULATED and is refused (in Python) until
;; both players have confirmed.
;;
;; All facts live in this plugin's space, &plugin-tennis.
;; =====================================================================

!(import! &self (library Omega ./plugins/tennis/tennis.py))
!(import_prolog_function msort)
!(import_prolog_function string_concat)
!(import_prolog_function swrite)

;; ---------- small helpers --------------------------------------------

(= (tn-cat $parts)
   (if (== $parts ())
       ""
       (string_concat (car-atom $parts) (tn-cat (cdr-atom $parts)))))

(= (tn-abs $x) (if (< $x 0) (- 0 $x) $x))

(= (tn-none $pattern-results) (== () $pattern-results))

;; ---------- MeTTa rule 1: level fit ----------------------------------
;; 3 points for the same level, 2 when within 0.2, 1 within half a level,
;; otherwise the pair is not a fit. Levels move as results are recorded.

(= (level-gap $a $b) (tn-abs (- $a $b)))

(= (level-fit $a $b)
   (let $gap (level-gap $a $b)
     (if (< $gap 0.01) 3
       (if (< $gap 0.21) 2
         (if (< $gap 0.51) 1 -1)))))

(= (level-reason $a $b)
   (let $fit (level-fit $a $b)
     (if (== $fit 3)
         (tn-cat ("level " $a " vs " $b " (same level)"))
         (if (== $fit 2)
             (tn-cat ("level " $a " vs " $b " (very close)"))
             (tn-cat ("level " $a " vs " $b " (half a level apart, still a fair match)"))))))

;; ---------- MeTTa rule 2: travel distance ----------------------------
;; Each player must be within their OWN max travel. Shorter combined trip
;; scores higher.

(= (within-travel $km $max) (<= $km $max))

(= (travel-score $ka $kb)
   (let $total (+ $ka $kb)
     (if (<= $total 4.0) 2
       (if (<= $total 8.0) 1 0))))

;; ---------- MeTTa rule 3: availability overlap -----------------------
;; A slot is usable when both players are available, the court is open,
;; and nothing in memory blocks it (court taken, player unavailable).

(= (court-blocked $court $day $hour)
   (not (tn-none (collapse (match &plugin-tennis (court-taken $court $day $hour) x)))))

(= (player-blocked $p $day $hour)
   (if (tn-none (collapse (match &plugin-tennis (unavailable $p $day $hour) x)))
       (not (tn-none (collapse (match &plugin-tennis (unavailable $p $day "all") x))))
       True))

(= (slot-free $a $b $court $day $hour)
   (if (court-blocked $court $day $hour) False
     (if (player-blocked $a $day $hour) False
       (not (player-blocked $b $day $hour)))))

;; ---------- preferences and history ----------------------------------

(= (surface-bonus $surf $pa $pb)
   (+ (if (== $surf $pa) 1 0) (if (== $surf $pb) 1 0)))

(= (played-before $a $b)
   (if (tn-none (collapse (match &plugin-tennis (played $a $b) x)))
       (not (tn-none (collapse (match &plugin-tennis (played $b $a) x))))
       True))

(= (rematch-penalty $a $b) (if (played-before $a $b) 1 0))

;; ---------- candidate generation -------------------------------------
;; Non-deterministic: yields every valid (opponent, court, day, hour).
;; Result: (cand NegScore Opp Court Day Hour TravelReq TravelOpp)
;; NegScore is negative so that msort puts the best match first.

(= (tennis-candidate $req)
   (match &plugin-tennis (player $req $rn $rl $rmax $rsurf $rarea)
     (match &plugin-tennis (player $opp $on $ol $omax $osurf $oarea)
       (tn-pair $req (eff-level $req $rl) $rmax $rsurf $opp (eff-level $opp $ol) $omax $osurf))))

;; ---------- memory of results: levels move with match results ----------
;; (rating player shift) holds how far a player's level has moved from their
;; profile level after matches played in the game. Clamped to +/- 0.5.
(= (rating-shift $p)
   (let $r (collapse (match &plugin-tennis (rating $p $s) $s))
     (if (== $r ()) 0.0 (car-atom $r))))
(= (tn-round1 $x) (/ (round-math (* $x 10)) 10.0))
(= (eff-level $p $base) (tn-round1 (+ $base (rating-shift $p))))
(= (tn-clamp $x) (if (> $x 0.5) 0.5 (if (< $x -0.5) -0.5 $x)))
(= (set-shift $p $new)
   (progn
     (collapse (match &plugin-tennis (rating $p $s) (remove-atom &plugin-tennis (rating $p $s))))
     (let $v (tn-clamp $new) (add-atom &plugin-tennis (rating $p $v)))))
(= (remember-match $w $l)
   (if (played-before $w $l) () (add-atom &plugin-tennis (played $w $l))))

;; Rule 1 gate: the pair must be a level fit.
(= (tn-pair $req $rl $rmax $rsurf $opp $ol $omax $osurf)
   (if (== $opp $req)
       (empty)
       (if (< (level-fit $rl $ol) 0)
           (empty)
           (match &plugin-tennis (available $req $day $hour)
             (tn-slot $req $rl $rmax $rsurf $opp $ol $omax $osurf $day $hour)))))

;; Rule 3: shared availability + an open court at that slot.
(= (tn-slot $req $rl $rmax $rsurf $opp $ol $omax $osurf $day $hour)
   (match &plugin-tennis (available $opp $day $hour)
     (match &plugin-tennis (court-open $court $day $hour)
       (tn-court $req $rl $rmax $rsurf $opp $ol $omax $osurf $day $hour $court))))

(= (tn-travel $p $c) (match &plugin-tennis (travel $p $c $km) $km))

;; Rule 3 (memory) + Rule 2 (travel) + scoring.
(= (tn-court $req $rl $rmax $rsurf $opp $ol $omax $osurf $day $hour $court)
   (if (not (slot-free $req $opp $court $day $hour))
       (empty)
       (let* (($rt (tn-travel $req $court))
              ($ot (tn-travel $opp $court)))
         (if (and (within-travel $rt $rmax) (within-travel $ot $omax))
             (let $score (- (+ (level-fit $rl $ol)
                               (+ (travel-score $rt $ot)
                                  (surface-bonus (court-surface $court) $rsurf $osurf)))
                            (rematch-penalty $req $opp))
               (cand (- 0 $score) $opp $court $day $hour $rt $ot))
             (empty)))))

(= (tennis-ranked $req)
   (msort (collapse (tennis-candidate $req))))

;; ---------- explanation ----------------------------------------------

(= (player-name $p) (match &plugin-tennis (player $p $n $l $m $s $a) $n))
(= (player-level $p) (match &plugin-tennis (player $p $n $l $m $s $a) (eff-level $p $l)))
(= (player-max $p) (match &plugin-tennis (player $p $n $l $m $s $a) $m))
(= (player-surface $p) (match &plugin-tennis (player $p $n $l $m $s $a) $s))
(= (court-name $c) (match &plugin-tennis (court $c $n $s) $n))
(= (court-surface $c) (match &plugin-tennis (court $c $n $s) $s))

(= (explain $req (cand $neg $opp $court $day $hour $rt $ot))
   (tn-cat ((player-name $opp) " at " (court-name $court) ", " $day " " $hour ":00"
            " [score " (- 0 $neg) "]. Why: "
            (level-reason (player-level $req) (player-level $opp)) "; "
            "travel " (player-name $req) " " $rt " km (max " (player-max $req) "), "
            (player-name $opp) " " $ot " km (max " (player-max $opp) "); "
            "both free " $day " " $hour ":00 and the court is open; "
            (court-surface $court) " court"
            (if (== (court-surface $court) (player-surface $req)) (tn-cat (", " (player-name $req) " prefers " (court-surface $court))) "")
            (if (== (court-surface $court) (player-surface $opp)) (tn-cat (", " (player-name $opp) " prefers " (court-surface $court))) "")
            (if (played-before $req $opp) "; small penalty: they played recently" ""))))

(= (explain-list $req $cands $n $i)
   (if (or (== $cands ()) (> $i $n))
       ""
       (tn-cat (" | Option " $i ": " (explain $req (car-atom $cands))
                (explain-list $req (cdr-atom $cands) $n (+ $i 1))))))

;; Pure reasoning entry point (used by the skill and by the tests).
(= (tennis-plan $req)
   (let $ranked (tennis-ranked $req)
     (if (== $ranked ())
         (tn-cat ("NO_MATCH for " $req ": no opponent, court and time satisfy level fit, travel limits and shared availability."))
         (tn-cat ("BEST " (explain $req (car-atom $ranked)) (explain-list $req (cdr-atom $ranked) 3 2))))))

;; ---------- conflict memory (asserted by skills) ---------------------

(= (tennis-court-taken-fact $court $day $hour)
   (add-atom &plugin-tennis (court-taken $court $day $hour)))

(= (tennis-unavailable-fact $player $day $hour)
   (add-atom &plugin-tennis (unavailable $player $day $hour)))

;; Omega hands a skill everything after its name as ONE string, e.g.
;; "tennis-court-taken alvalade sat 18" -> (tennis-court-taken "alvalade sat 18").
;; tennis.py splits and normalises it (names -> ids, saturday -> sat, 18:00 -> 18).
(= (tn-arg $args $i) (swrite (py-call (tennis.arg $args $i))))
(= (tn-hour-arg $args $i)
   (let $h (py-call (tennis.hour_arg $args $i))
     (if (== $h -1) "all" $h)))

;; ---------- Omega skills ---------------------------------------------

(= (tennis-propose $args)
   (let $player (tn-arg $args 0)
     (let $plan (tennis-plan $player)
       (progn
         (py-call (tennis.publish_plan $player $plan))
         $plan))))

(= (tennis-court-taken $args)
   (let* (($court (tn-arg $args 0))
          ($day (tn-arg $args 1))
          ($hour (tn-hour-arg $args 2)))
     (progn
       (tennis-court-taken-fact $court $day $hour)
       (py-call (tennis.publish_event "court_taken" $args))
       (tn-cat ("Recorded in memory: court " $court " is taken on " $day " " $hour ":00. Now call tennis-propose again to re-plan.")))))

(= (tennis-player-unavailable $args)
   (let* (($player (tn-arg $args 0))
          ($day (tn-arg $args 1))
          ($hour (tn-hour-arg $args 2)))
     (progn
       (tennis-unavailable-fact $player $day $hour)
       (py-call (tennis.publish_event "player_unavailable" $args))
       (tn-cat ("Recorded in memory: " $player " is unavailable on " $day " (hour " $hour "). Now call tennis-propose again to re-plan.")))))

(= (tennis-request-confirmation $args)
   (py-call (tennis.request_confirmation $args)))

;; The Python side refuses unless both players confirmed. A successful
;; booking is also remembered here, so later plans skip that slot.
;; Called when a match played in the game ends: "winner loser games_w games_l".
;; Records the match and moves both levels by 0.1, so future proposals change.
(= (tennis-record-result $args)
   (let* (($w (tn-arg $args 0))
          ($l (tn-arg $args 1))
          ($gw (tn-arg $args 2))
          ($gl (tn-arg $args 3)))
     (progn
       (remember-match $w $l)
       (set-shift $w (+ (rating-shift $w) 0.1))
       (set-shift $l (- (rating-shift $l) 0.1))
       (py-call (tennis.publish_ratings $w (player-level $w) $l (player-level $l)))
       (tn-cat ("Recorded in memory: " (player-name $w) " beat " (player-name $l) " " $gw "-" $gl
                ". Levels now " (player-name $w) " " (player-level $w) ", " (player-name $l) " " (player-level $l)
                ". Future proposals use these levels and remember this match.")))))

(= (tennis-book $args)
   (let $result (py-call (tennis.book $args))
     (if (== (py-call (tennis.is_booked $result)) yes)
         (progn
           (tennis-court-taken-fact (tn-arg $args 2) (tn-arg $args 3) (tn-hour-arg $args 4))
           $result)
         $result)))

(= (loadOmegaPlugin)
   (progn
     (log INFO "tennis-plugin" "World Tennis match coordinator loaded")
     (add-skill tennis-propose "World Tennis: rank opponent, court and time for a player using MeTTa rules (level fit, travel, shared availability). Always use this instead of guessing" (player_id))
     (add-skill tennis-court-taken "World Tennis: record that a court slot is no longer free, then re-plan" (court_id day hour))
     (add-skill tennis-player-unavailable "World Tennis: record that a player cannot play a slot (hour may be all), then re-plan" (player_id day hour))
     (add-skill tennis-request-confirmation "World Tennis: ask BOTH players to confirm a proposed match before any booking" (player_a player_b court_id day hour))
     (add-skill tennis-book "World Tennis: make a SIMULATED booking. Only after both players confirmed; refused otherwise" (player_a player_b court_id day hour))
     (add-skill tennis-record-result "World Tennis: record a finished match from the game and update both levels" (winner_id loser_id winner_games loser_games))
     (add-prompt-extension tennis_rules "WORLD TENNIS COORDINATOR: you match players for tennis using ONLY the tennis-* skills. Player ids: ana joao sara kofi mei lucas. Court ids: alvalade estrela monsanto oriente. Days: sat sun. Messages arrive as [Name]: text; the name is who is speaking. Hours are numbers like 18. Skill call examples: tennis-propose ana | tennis-court-taken alvalade sat 18 | tennis-player-unavailable joao sat all | tennis-request-confirmation ana joao alvalade sat 19 | tennis-book ana joao alvalade sat 19. Use send to talk to the players. When asked for a match call tennis-propose and explain the BEST option with its reasons. When told about a clash (court taken, player unavailable) record it with tennis-court-taken or tennis-player-unavailable, then call tennis-propose again and explain what changed. Before booking ALWAYS call tennis-request-confirmation and wait for both CONFIRMED messages. Bookings and payments are SIMULATED: say so. Never say a match is booked unless tennis-book returned BOOKED. Send ONE short message per update, addressed to both players, never one copy per player. Do not repeat a message you already sent. When a [Match system] MATCH RESULT message arrives, call tennis-record-result with the ids and games it gives, then send ONE short message with the result, the new levels and one coaching tip for the loser. When a [Coach request] arrives, send ONE tactical tip of at most 20 words for that player, based only on the stats given; do not call other skills for it. Remember each player's preferences and past matches with remember.")
     ()))

;; ---- BEGIN GENERATED FACTS (scripts/gen_facts.py) ----
;; SAMPLE DATA ONLY - invented players and courts, no real player data.
;; (player id name level max-travel-km preferred-surface area)
(player "ana" "Ana" 3.5 5.0 "clay" "Alvalade")
(player "joao" "Joao" 3.5 6.0 "hard" "Arroios")
(player "sara" "Sara" 3.5 7.0 "clay" "Benfica")
(player "kofi" "Kofi" 4.0 4.0 "hard" "Belem")
(player "mei" "Mei" 3.0 8.0 "hard" "Parque das Nacoes")
(player "lucas" "Lucas" 4.5 6.0 "clay" "Campo de Ourique")
;; (available player day hour)
(available "ana" "sat" 9)
(available "ana" "sat" 10)
(available "ana" "sat" 18)
(available "ana" "sat" 19)
(available "ana" "sun" 10)
(available "joao" "sat" 18)
(available "joao" "sat" 19)
(available "joao" "sun" 10)
(available "joao" "sun" 11)
(available "sara" "sat" 18)
(available "sara" "sat" 19)
(available "sara" "sun" 11)
(available "kofi" "sat" 9)
(available "kofi" "sat" 10)
(available "kofi" "sun" 9)
(available "mei" "sat" 18)
(available "mei" "sun" 10)
(available "mei" "sun" 11)
(available "lucas" "sat" 10)
(available "lucas" "sat" 19)
(available "lucas" "sun" 9)
;; (court id name surface) and (court-open court day hour)
(court "alvalade" "CT Alvalade (Court 2)" "clay")
(court-open "alvalade" "sat" 9)
(court-open "alvalade" "sat" 10)
(court-open "alvalade" "sat" 18)
(court-open "alvalade" "sat" 19)
(court-open "alvalade" "sun" 10)
(court-open "alvalade" "sun" 11)
(court "estrela" "Estrela Tennis Club" "hard")
(court-open "estrela" "sat" 10)
(court-open "estrela" "sat" 18)
(court-open "estrela" "sat" 19)
(court-open "estrela" "sun" 9)
(court-open "estrela" "sun" 10)
(court-open "estrela" "sun" 11)
(court "monsanto" "Monsanto Park Courts" "clay")
(court-open "monsanto" "sat" 9)
(court-open "monsanto" "sat" 10)
(court-open "monsanto" "sat" 19)
(court-open "monsanto" "sun" 9)
(court-open "monsanto" "sun" 11)
(court "oriente" "Oriente Riverside Club" "hard")
(court-open "oriente" "sat" 18)
(court-open "oriente" "sat" 19)
(court-open "oriente" "sun" 10)
(court-open "oriente" "sun" 11)
;; (travel player court km) - straight-line km on the sample map
(travel "ana" "alvalade" 0.5)
(travel "ana" "estrela" 4.9)
(travel "ana" "monsanto" 5.4)
(travel "ana" "oriente" 4.5)
(travel "joao" "alvalade" 3.5)
(travel "joao" "estrela" 2.9)
(travel "joao" "monsanto" 5.0)
(travel "joao" "oriente" 6.1)
(travel "sara" "alvalade" 3.5)
(travel "sara" "estrela" 4.7)
(travel "sara" "monsanto" 3.2)
(travel "sara" "oriente" 7.8)
(travel "kofi" "alvalade" 9.6)
(travel "kofi" "estrela" 5.2)
(travel "kofi" "monsanto" 3.9)
(travel "kofi" "oriente" 13.6)
(travel "mei" "alvalade" 4.7)
(travel "mei" "estrela" 9.6)
(travel "mei" "monsanto" 10.4)
(travel "mei" "oriente" 1.0)
(travel "lucas" "alvalade" 5.4)
(travel "lucas" "estrela" 1.1)
(travel "lucas" "monsanto" 1.8)
(travel "lucas" "oriente" 9.2)
;; (played a b) - past matches
(played "ana" "sara")
;; ---- END GENERATED FACTS ----
