-- Replies (as a draft) to the most recent message from an address, in the
-- same thread. Never sends.
--
-- Run: osascript outlook_reply.applescript <fromAddress> <bodyHTML> <daysBack>
-- Prints "ok" when a reply draft was opened, "none" when no message from that
-- address was found (the caller then opens a fresh email instead).

on run argv
	set fromAddress to item 1 of argv
	set theBody to item 2 of argv
	set daysBack to 60
	try
		set daysBack to (item 3 of argv) as integer
	end try
	set cutoff to (current date) - (daysBack * days)

	tell application "Microsoft Outlook"
		set newest to missing value
		set newestTime to cutoff
		set msgs to (messages of inbox whose time received > cutoff)
		repeat with m in msgs
			try
				if (address of sender of m) is fromAddress then
					set t to time received of m
					if t > newestTime then
						set newest to m
						set newestTime to t
					end if
				end if
			end try
		end repeat
		if newest is missing value then return "none"
		activate
		set r to reply to newest without opening window
		set content of r to theBody & (content of r)
		open r
	end tell
	return "ok"
end run
