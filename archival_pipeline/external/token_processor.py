# -*- coding: utf-8 -*-

# Bulk Rename Py
# © 2026–present Codemorra (Christopher Kranz)
# Licensed under the MIT License (see LICENSE file)

"""Token processing and mask application.

Handles replacement of placeholder tokens in filename masks,
supporting tokens like {name}, {ext}, {counter}, {date}, {time},
and their variants with slicing (e.g., {name1-3}, {ext1-2}).
"""

import re
from pathlib import Path
from typing import Tuple, Dict, List, Optional
from datetime import datetime


# Patterns
_LITERAL_BRACES_PATTERN = re.compile(r'\{\{\}([^{}]+)\{\}\}')
_TOKEN_PATTERN = re.compile(r'\{([^\{\}]+)\}')


class TokenProcessor:
    """Token processing and mask application operations.

    Handles replacement of placeholder tokens in filename masks.

    All methods are static as no instance state is required.
    """


######################
# MAIN FUNCTIONALITY #
######################
    @staticmethod
    def apply_name_mask(
            mask: str,
            oname: str,
            ext: str,
            counter: str,
            date_str: str,
            time_str: str,
            path: Optional[Path] = None,
            date_type: str = 'current'
    ) -> str:
        """Apply placeholders in name mask.

        Replaces tokens like {name}, {ext}, {counter}, {date}, {time} with actual values.

        **Parameters:**
            `mask` (str): Name mask with placeholders
            `oname` (str): Original base name
            `ext` (str): Original file extension
            `counter` (str): Formatted counter
            `date_str` (str): Formatted date
            `time_str` (str): Formatted time
            `path` (Optional[Path]): File path for date_type='change'
            `date_type` (str): Date source ("current" or "change")

        **Returns:**
            `str`: Result after applying mask

        **Supported tokens:**
            {name}, {nameX-Y}: Current filename with optional slicing
            {ext}, {extX-Y}: File extension with optional slicing
            {counter}: Numeric counter
            {date}: Date string
            {time}: Time string
        """
        # Escape literal braces to prevent them from being processed as tokens
        esc_mask, litmap = TokenProcessor._escape_literal_braces(mask)

        def _repl(m: re.Match) -> str:
            tok = m.group(1)

            # Handle {name} and {nameX-Y} tokens
            if tok == 'name':
                return oname
            if tok.startswith('name'):
                spec = tok[4:]
                if spec and re.fullmatch(r'(\d+|\*)-(\d+|\*)', spec):
                    return TokenProcessor._slice_token(oname, spec)
                return f'{{{tok}}}'

            # Handle {ext} and {extX-Y} tokens
            if tok == 'ext':
                return ext
            if tok.startswith('ext'):
                spec = tok[3:]
                if spec and re.fullmatch(r'(\d+|\*)-(\d+|\*)', spec):
                    return TokenProcessor._slice_token(ext, spec)
                return f'{{{tok}}}'

            # Handle simple tokens
            if tok == 'counter':
                return counter
            if tok == 'date':
                return date_str
            if tok == 'time':
                return time_str

            # Handle custom date/time format patterns
            if TokenProcessor._is_custom_date_format(tok):
                return TokenProcessor._format_custom_date(tok, date_str, time_str, path, date_type)
            elif TokenProcessor._is_custom_time_format(tok):
                return TokenProcessor._format_custom_time(tok, time_str, path, date_type)

            # Return unknown tokens unchanged
            return f'{{{tok}}}'

        # Apply token replacement and restore literal braces
        result = _TOKEN_PATTERN.sub(_repl, esc_mask)
        result = TokenProcessor._restore_literal_braces(result, litmap)

        return result

    @staticmethod
    def apply_case_transform(text: str, mode: str) -> str:
        """Apply case transformation to text.

        **Parameters:**
            `text` (str): Text to transform
            `mode` (str): Transformation mode

        **Returns:**
            `str`: Transformed text

        **Supported modes:**
            lowercase: Convert to lowercase
            uppercase: Convert to uppercase
            heading: Capitalize first letter
            mocking: AlTeRnAtInG cAsE
            other: Return unchanged
        """
        # Apply case transformation based on mode
        if mode == 'lowercase':
            return text.lower()
        elif mode == 'uppercase':
            return text.upper()
        elif mode == 'heading':
            return text.capitalize()
        elif mode == 'mocking':
            # Create alternating case pattern
            return ''.join(
                ch.upper() if i % 2 == 0 else ch.lower()
                for i, ch in enumerate(text)
            )
        return text


##################
# HELPER METHODS #
##################
    @staticmethod
    def _escape_literal_braces(mask: str) -> Tuple[str, Dict[str, str]]:
        """Escape literal brace segments in mask.

        Converts segments like {{}name{}} to temporary placeholders.

        **Parameters:**
            `mask` (str): Input mask containing tokens and literal braces

        **Returns:**
            `Tuple[str, Dict[str, str]]`: Modified mask and mapping of placeholders to original content
        """
        litmap = {}

        def _repl(m: re.Match) -> str:
            key = f"__LITERAL_{len(litmap)}__"
            litmap[key] = m.group(0)
            return key

        return _LITERAL_BRACES_PATTERN.sub(_repl, mask), litmap

    @staticmethod
    def _restore_literal_braces(text: str, mapping: Dict[str, str]) -> str:
        """Restore literal brace markers.

        **Parameters:**
            `text` (str): Text containing __LITERAL_i__ markers
            `mapping` (Dict[str, str]): Placeholder to original literal mapping

        **Returns:**
            `str`: Text with restored literal braces
        """
        for key, val in mapping.items():
            text = text.replace(key, val)

        return text

    @staticmethod
    def _slice_token(text: str, spec: str) -> str:
        """Extract substring using range specification.

        **Parameters:**
            `text` (str): Source text
            `spec` (str): Range specification (start-end)

        **Returns:**
            `str`: Extracted substring or original text if invalid

        **Examples:**
            "1-3" → characters 1 to 3
            "4-*" → from character 4 to end
            "*-5" → from start to character 5
            "*-*" → full text
        """
        # Parse range specification and extract substring
        spec = spec.strip()
        m = re.fullmatch(r'(\d+|\*)-(\d+|\*)', spec)
        if not m:
            return text
        
        # Convert range specification to indices
        left, right = m.groups()
        start = 1 if left == '*' else max(1, int(left))
        end = len(text) if right == '*' else int(right)
        
        # Return sliced substring (Python uses 0-based indexing)
        return text[start-1:end]

    @staticmethod
    def _is_custom_date_format(tok: str) -> bool:
        """Check if token is a custom date format.

        **Parameters:**
            `tok` (str): Token to check

        **Returns:**
            `bool`: True if token matches custom date format pattern
        """
        # Check for patterns like yyyy-mm-dd, dd.mm.yyyy, yyyymmdd, etc.
        # Support separators: - _ . ; space : or no separator
        return bool(re.fullmatch(r'(yyyy|yy|mm|dd)([\-._; :]?)((yyyy|yy|mm|dd)([\-._; :]?)(yyyy|yy|mm|dd))?', tok))

    @staticmethod
    def _is_custom_time_format(tok: str) -> bool:
        """Check if token is a custom time format.

        **Parameters:**
            `tok` (str): Token to check

        **Returns:**
            `bool`: True if token matches custom time format pattern
        """
        # Check for patterns like hh-mm-ss, hh.mm, hhmmss, etc.
        # Support separators: - _ . ; space : or no separator
        return (bool(re.fullmatch(r'(hh|mm|ss)([\-._; :]?)(hh|mm|ss)([\-._; :]?)(hh|mm|ss)', tok)) or
                bool(re.fullmatch(r'(hh|mm|ss)([\-._; :]?)(hh|mm|ss)', tok)) or
                bool(re.fullmatch(r'(hh|mm|ss)', tok)))

    @staticmethod
    def _format_custom_date(format_pattern: str, date_str: str, time_str: str, path: Optional[Path] = None, date_type: str = 'current') -> str:
        """Format date according to custom pattern.

        **Parameters:**
            `format_pattern` (str): Custom format pattern (e.g., 'yyyy-mm-dd')
            `date_str` (str): Pre-formatted date string from configuration
            `time_str` (str): Pre-formatted time string (unused for date)
            `path` (Optional[Path]): File path for date_type='change'
            `date_type` (str): Date source ("current" or "change")

        **Returns:**
            `str`: Formatted date string or original token if pattern is invalid
        """
        # Parse the custom format pattern
        try:
            # Replace common format placeholders with strftime format codes
            pattern = format_pattern
            pattern = pattern.replace('yyyy', '%Y')
            pattern = pattern.replace('yy', '%y')
            pattern = pattern.replace('mm', '%m')
            pattern = pattern.replace('dd', '%d')

            # Get datetime based on date_type
            if date_type == 'change' and path:
                try:
                    ts = path.stat().st_mtime
                    dt = datetime.fromtimestamp(ts)
                except (FileNotFoundError, OSError, PermissionError):
                    dt = datetime.now()
            else:
                dt = datetime.now()
            
            # Format using the parsed pattern
            return dt.strftime(pattern)
        except (ValueError, AttributeError):
            # Return original token if formatting fails
            return f'{{{format_pattern}}}'

    @staticmethod
    def _format_custom_time(format_pattern: str, time_str: str, path: Optional[Path] = None, date_type: str = 'current') -> str:
        """Format time according to custom pattern.

        **Parameters:**
            `format_pattern` (str): Custom format pattern (e.g., 'hh-mm-ss')
            `time_str` (str): Pre-formatted time string from configuration
            `path` (Optional[Path]): File path for date_type='change'
            `date_type` (str): Date source ("current" or "change")

        **Returns:**
            `str`: Formatted time string or original token if pattern is invalid
        """
        # Parse the custom format pattern
        try:
            # Replace common format placeholders with strftime format codes
            pattern = format_pattern
            pattern = pattern.replace('hh', '%H')
            pattern = pattern.replace('mm', '%M')
            pattern = pattern.replace('ss', '%S')

            # Get datetime based on date_type
            if date_type == 'change' and path:
                try:
                    ts = path.stat().st_mtime
                    dt = datetime.fromtimestamp(ts)
                except (FileNotFoundError, OSError, PermissionError):
                    dt = datetime.now()
            else:
                dt = datetime.now()
            
            # Format using the parsed pattern
            return dt.strftime(pattern)
        except (ValueError, AttributeError):
            # Return original token if formatting fails
            return f'{{{format_pattern}}}'

