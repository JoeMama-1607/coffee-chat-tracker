-- Fallback draft creator using the `content` property.
--
-- Run: osascript outlook_draft.applescript <toAddress> <toName> <subject> <body> <attachmentPath>

on run argv
	set toAddress to item 1 of argv
	set toName to item 2 of argv
	set theSubject to item 3 of argv
	set theBody to item 4 of argv
	set attachPath to ""
	try
		set attachPath to item 5 of argv
	end try

	tell application "Microsoft Outlook"
		activate
		set newMessage to make new outgoing message with properties {subject:theSubject, content:theBody}
		make new recipient at newMessage with properties {email address:{name:toName, address:toAddress}}
		if attachPath is not "" then
			try
				make new attachment at newMessage with properties {file:(POSIX file attachPath)}
			end try
		end if
		open newMessage
	end tell
	return "ok"
end run
