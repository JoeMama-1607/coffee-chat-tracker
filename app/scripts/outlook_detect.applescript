-- Reports whether the Outlook on this Mac can be scripted.
-- Output: "classic<TAB>version" | "unscriptable<TAB>reason" | "missing<TAB>reason"
--
-- "New Outlook" for Mac ships without an AppleScript dictionary, so the
-- mail-tracking features degrade gracefully and the app says so plainly.

on run
	try
		tell application "System Events"
			if not (exists application process "Microsoft Outlook") then
				-- not running is fine; we only need it installed
			end if
		end tell
	end try

	try
		tell application "Microsoft Outlook"
			set v to version as string
			-- `mail folders` only exists in the classic scripting dictionary
			set folderCount to count of mail folders
			return "classic" & tab & v & tab & (folderCount as string)
		end tell
	on error errMsg number errNum
		if errNum is -1728 or errNum is -1708 or errNum is -10004 then
			return "unscriptable" & tab & "Outlook is installed but not scriptable (this is the \"new Outlook\" interface). Error " & (errNum as string)
		else if errNum is -1743 then
			return "unauthorized" & tab & "macOS has not granted automation access to Outlook yet. Approve the prompt, or enable it in System Settings > Privacy & Security > Automation."
		else
			return "missing" & tab & (errMsg as string) & " (" & (errNum as string) & ")"
		end if
	end try
end run
