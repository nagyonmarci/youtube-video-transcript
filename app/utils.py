import json
import time

def json_to_netscape(json_cookies):
    """
    Converts a list of JSON cookies (often from browser extensions) to Netscape format.
    """
    if isinstance(json_cookies, str):
        try:
            json_cookies = json.loads(json_cookies)
        except json.JSONDecodeError:
            return json_cookies # Return as is, might already be Netscape

    if not isinstance(json_cookies, list):
        return json_cookies

    netscape_lines = ["# Netscape HTTP Cookie File", "# http://curl.haxx.se/rfc/cookie_spec.html", "# This is a generated file!  Do not edit.", ""]
    
    for cookie in json_cookies:
        # Standard Netscape fields: 
        # domain, flag, path, secure, expiration, name, value
        
        domain = cookie.get("domain", "")
        # Flag: TRUE if all machines in the domain can access, FALSE otherwise
        # Usually TRUE for domains starting with .
        flag = "TRUE" if domain.startswith(".") else "FALSE"
        
        path = cookie.get("path", "/")
        secure = "TRUE" if cookie.get("secure") else "FALSE"
        
        # Expiration (timestamp)
        # Note: some extensions use 'expirationDate', others 'expiry'
        expiration = int(cookie.get("expirationDate") or cookie.get("expiry") or (time.time() + 31536000))
        
        name = cookie.get("name", "")
        value = cookie.get("value", "")
        
        line = f"{domain}\t{flag}\t{path}\t{secure}\t{expiration}\t{name}\t{value}"
        netscape_lines.append(line)
        
    return "\n".join(netscape_lines)
