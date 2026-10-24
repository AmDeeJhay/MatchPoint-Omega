
;; ---- standalone rule tests (appended after the plugin by scripts/test_rules.sh) ----
!(println! (level-fit 3.5 3.5))
!(println! (level-fit 3.5 4.0))
!(println! (level-fit 3.0 4.5))
!(println! (tennis-ranked "ana"))
!(println! (tennis-plan "ana"))
;; conflict 1: the best court slot gets taken
!(add-atom &plugin-tennis (court-taken "alvalade" "sat" 18))
!(println! (tennis-plan "ana"))
;; conflict 2: Joao becomes unavailable all Saturday
!(add-atom &plugin-tennis (unavailable "joao" "sat" "all"))
!(println! (tennis-plan "ana"))
!(println! (tennis-plan "lucas"))
;; results move levels and are remembered
!(println! (eff-level "ana" 3.5))
!(remember-match "ana" "joao")
!(set-shift "ana" (+ (rating-shift "ana") 0.1))
!(set-shift "joao" (- (rating-shift "joao") 0.1))
!(println! (player-level "ana"))
!(println! (player-level "joao"))
!(println! (played-before "joao" "ana"))
!(println! (tennis-plan "ana"))
