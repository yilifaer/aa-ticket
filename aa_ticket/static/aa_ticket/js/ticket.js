/* aa-ticket: small helpers for the ticket forms. No external libraries. */
(function () {
    "use strict";

    function insertAtCursor(textarea, text) {
        var start = textarea.selectionStart || 0;
        var end = textarea.selectionEnd || 0;
        var value = textarea.value;
        textarea.value = value.slice(0, start) + text + value.slice(end);
        var pos = start + text.length;
        textarea.focus();
        textarea.setSelectionRange(pos, pos);
    }

    document.addEventListener("DOMContentLoaded", function () {
        var category = document.querySelector("[data-ticket-category]");
        var body = document.querySelector("[data-ticket-body]");
        if (category && body) {
            category.addEventListener("change", function () {
                var option = category.options[category.selectedIndex];
                var template = option ? option.getAttribute("data-template") : "";
                if (template && body.value.trim() === "") {
                    body.value = template;
                }
            });
        }

        var canned = document.querySelector("[data-ticket-canned]");
        var reply = document.querySelector("[data-ticket-reply]");
        if (canned && reply) {
            canned.addEventListener("change", function () {
                if (canned.value) {
                    insertAtCursor(reply, canned.value);
                }
                canned.selectedIndex = 0;
            });
        }

        var files = document.querySelector("[data-ticket-files]");
        var filesLabel = document.querySelector("[data-ticket-files-label]");
        if (files && filesLabel) {
            files.addEventListener("change", function () {
                var names = [];
                for (var i = 0; i < files.files.length; i++) {
                    names.push(files.files[i].name);
                }
                filesLabel.textContent = names.join(", ");
            });
        }
    });
})();
