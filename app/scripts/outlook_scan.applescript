-- Scans classic Outlook for Mac for recent mail, so the tracker can tell who
-- has replied and who has gone quiet.
--
-- Run: osascript outlook_scan.applescript <daysBack> <maxMessages>
-- Output: one record per line, tab separated:
--     direction <TAB> secondsFromNow <TAB> counterpartAddress <TAB> subject
-- `secondsFromNow` is negative for the past; the caller converts it to a real
-- timestamp using its own clock, which avoids all AppleScript date parsing.
-- A line beginning with "#" is a diagnostic, not a message.

on cleanText(theText)
	try
		set theText to theText as string
	on error
		return ""
	end try
	set out to ""
	repeat with c in the characters of theText
		set ch to c as string
		if ch is tab or ch is return or ch is linefeed then
			set out to out & " "
		else
			set out to out & ch
		end if
	end repeat
	return out
end cleanText

on run argv
	set daysBack to 30
	set maxMessages to 400
	try
		set daysBack to (item 1 of argv) as integer
	end try
	try
		set maxMessages to (item 2 of argv) as integer
	end try

	set nowD to current date
	set cutoff to nowD - (daysBack * days)
	set results to {}
	set diagnostics to {}

	tell application "Microsoft Outlook"

		-- ---------------------------------------------------------- inbox
		try
			set inboxMsgs to (messages of inbox whose time received > cutoff)
			set n to count of inboxMsgs
			if n > maxMessages then set n to maxMessages
			repeat with i from 1 to n
				try
					set m to item i of inboxMsgs
					set addr to ""
					try
						set addr to address of sender of m
					end try
					if addr is not "" then
						set delta to ((time received of m) - nowD) as integer
						set subj to my cleanText(subject of m)
						set end of results to ("in" & tab & (delta as string) & tab & addr & tab & subj)
					end if
				end try
			end repeat
			set end of diagnostics to ("# inbox scanned: " & (n as string))
		on error errMsg number errNum
			set end of diagnostics to ("# inbox failed: " & errMsg & " (" & (errNum as string) & ")")
		end try

		-- ----------------------------------------------------- sent items
		-- Located by name rather than by a dictionary term, because the
		-- property name for the sent folder differs between Outlook builds.
		set sentFolder to missing value
		try
			repeat with f in mail folders
				try
					set fname to name of f as string
					if fname is "Sent Items" or fname is "Sent" or fname is "Sent Mail" then
						set sentFolder to f
						exit repeat
					end if
				end try
			end repeat
		end try
		if sentFolder is missing value then
			try
				repeat with f in mail folders
					try
						repeat with sub in mail folders of f
							set sname to name of sub as string
							if sname is "Sent Items" or sname is "Sent" or sname is "Sent Mail" then
								set sentFolder to sub
								exit repeat
							end if
						end repeat
					end try
					if sentFolder is not missing value then exit repeat
				end repeat
			end try
		end if

		if sentFolder is missing value then
			set end of diagnostics to "# sent folder not found"
		else
			try
				set sentMsgs to (messages of sentFolder whose time sent > cutoff)
				set n to count of sentMsgs
				if n > maxMessages then set n to maxMessages
				repeat with i from 1 to n
					try
						set m to item i of sentMsgs
						set delta to ((time sent of m) - nowD) as integer
						set subj to my cleanText(subject of m)
						repeat with r in to recipients of m
							try
								set addr to address of email address of r
								set end of results to ("out" & tab & (delta as string) & tab & addr & tab & subj)
							end try
						end repeat
					end try
				end repeat
				set end of diagnostics to ("# sent scanned: " & (n as string))
			on error errMsg number errNum
				set end of diagnostics to ("# sent failed: " & errMsg & " (" & (errNum as string) & ")")
			end try
		end if

	end tell

	set AppleScript's text item delimiters to linefeed
	set payload to (diagnostics as string)
	if (count of results) > 0 then
		set payload to payload & linefeed & (results as string)
	end if
	set AppleScript's text item delimiters to ""
	return payload
end run
