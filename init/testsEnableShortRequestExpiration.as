;;
;;	testEnableShortRequestExpiration.as
;;
;;	This script is supposed to be called by the test system via the upper tester interface
;;

@name enableShortRequestExpiration
@description (Tests) Enable shorter request expirations
@usage enableShortRequestExpiration <seconds>
@uppertester

(if (!= argc 2)
	(	(log-error "Wrong number of arguments: enableShortRequestExpiration <expirationTimeout>")
		(quit-with-error)))

(include-script "functions")

(set-and-store-config-saved "cse.requestExpirationDelta" (to-number (argv 1)))

;; return the original expiration delta
(quit (get-storage "cse.requestExpirationDelta"))
