-- Opens a meeting invite in classic Outlook for Mac, ready to send. Never sends.
--
-- Run: osascript outlook_invite.applescript <toAddress> <toName> <subject>
--        <bodyHTML> <startSecondsFromNow> <durationMinutes> <location> <attachmentPath>
-- The start is passed as seconds from now (the caller's clock) so no
-- AppleScript date parsing is involved. Prints "ok attached" or "ok no-attachment".

on run argv
	set toAddress to item 1 of argv
	set toName to item 2 of argv
	set theSubject to item 3 of argv
	set theBody to item 4 of argv
	set startOffset to (item 5 of argv) as integer
	set durationMins to (item 6 of argv) as integer
	set theLocation to item 7 of argv
	set attachPath to ""
	try
		set attachPath to item 8 of argv
	end try

	set startD to (current date) + startOffset
	set endD to startD + (durationMins * minutes)
	set attached to "no-attachment"

	tell application "Microsoft Outlook"
		activate
		set newEvent to make new calendar event with properties {subject:theSubject, start time:startD, end time:endD, location:theLocation, content:theBody}
		make new required attendee at newEvent with properties {email address:{name:toName, address:toAddress}}
		if attachPath is not "" then
			try
				make new attachment at newEvent with properties {file:(POSIX file attachPath)}
				set attached to "attached"
			end try
		end if
		open newEvent
	end tell
	return "ok " & attached
end run
