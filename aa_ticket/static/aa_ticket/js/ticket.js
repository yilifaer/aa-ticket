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
            var lastTemplate = "";
            category.addEventListener("change", function () {
                var option = category.options[category.selectedIndex];
                var template = option ? option.getAttribute("data-template") || "" : "";
                // fill in the template while the text is still empty or an untouched earlier template
                if (body.value.trim() === "" || body.value === lastTemplate) {
                    body.value = template;
                    lastTemplate = template;
                }
            });
        }

        var once = document.querySelectorAll("form[data-submit-once]");
        for (var k = 0; k < once.length; k++) {
            once[k].addEventListener("submit", function (event) {
                var form = event.currentTarget;
                if (form.getAttribute("data-submitted")) {
                    event.preventDefault();
                    return;
                }
                form.setAttribute("data-submitted", "1");
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
