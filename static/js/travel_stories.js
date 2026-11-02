
document.addEventListener("DOMContentLoaded", () => {
    initStoryPublishing();
    initStoryComments();
});


function initStoryPublishing() {
    const form = document.querySelector("#travel-story-form");

    if (!form) return;

    const submitButton = form.querySelector('button[type="submit"]');
    const messageBox = document.querySelector("#story-form-message");

    const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
    const MAX_GALLERY_IMAGES = 10;
    const ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp"];

    function showMessage(message, type = "error") {
        if (!messageBox) return;

        messageBox.textContent = message;
        messageBox.className = `story-form-message ${type}`;
        messageBox.hidden = false;
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();

        const title = form.elements.title.value.trim();
        const destination = form.elements.destination.value.trim();
        const country = form.elements.country.value.trim();
        const content = form.elements.content.value.trim();
        const csrfToken = form.elements.csrf_token.value;

        const coverInput = form.elements.cover_image;
        const galleryInput = form.elements.gallery_images;

        const coverImage = coverInput.files[0] || null;
        const galleryImages = Array.from(galleryInput.files);

        if (title.length < 5 || title.length > 180) {
            showMessage("Title must be between 5 and 180 characters.");
            return;
        }

        if (destination.length < 2 || destination.length > 150) {
            showMessage("Please enter a valid destination.");
            return;
        }

        if (country.length < 2 || country.length > 100) {
            showMessage("Please enter a valid country.");
            return;
        }

        if (content.length < 50 || content.length > 50000) {
            showMessage("Your story must be between 50 and 50,000 characters.");
            return;
        }

        if (!csrfToken) {
            showMessage("Your security token is missing. Please refresh the page.");
            return;
        }

        if (galleryImages.length > MAX_GALLERY_IMAGES) {
            showMessage("You can select a maximum of 10 gallery photos.");
            return;
        }

        const selectedImages = [
            ...(coverImage ? [coverImage] : []),
            ...galleryImages
        ];

        for (const image of selectedImages) {
            if (!ALLOWED_TYPES.includes(image.type)) {
                showMessage("Only JPEG, PNG and WebP images are allowed.");
                return;
            }

            if (image.size > MAX_IMAGE_BYTES) {
                showMessage(`"${image.name}" exceeds the 5 MB image limit.`);
                return;
            }

            if (image.size === 0) {
                showMessage(`"${image.name}" is empty.`);
                return;
            }
        }

        const formData = new FormData();

        formData.append("csrf_token", csrfToken);
        formData.append("title", title);
        formData.append("destination", destination);
        formData.append("country", country);
        formData.append("content", content);

        if (coverImage) {
            formData.append("cover_image", coverImage);
        }

        for (const image of galleryImages) {
            formData.append("gallery_images", image);
        }

        submitButton.disabled = true;
        submitButton.textContent = "Publishing...";

        try {
            const response = await fetch("/api/travel-stories", {
                method: "POST",
                headers: {
                    "X-CSRF-Token": csrfToken
                },
                body: formData
            });

            const result = await response.json();

            if (!response.ok) {
                showMessage(result.error || "Unable to publish your story.");
                return;
            }

            showMessage("Your travel story has been published!", "success");

            if (result.story && result.story.url) {
                window.location.assign(result.story.url);
            }

        } catch (error) {
            console.error("Travel story submission failed:", error);
            showMessage("A connection error occurred. Please try again.");
        } finally {
            submitButton.disabled = false;
            submitButton.textContent = "Publish my story";
        }
    });
}


function initStoryComments() {
    const container = document.querySelector("#story-comments");

    if (!container) return;

    const storyId = container.dataset.storyId;
    const authenticated = container.dataset.authenticated === "true";
    const csrfToken = container.dataset.csrfToken;

    const commentList = document.querySelector("#comment-list");
    const commentCount = document.querySelector("#comment-count");
    const commentForm = document.querySelector("#story-comment-form");
    const commentInput = document.querySelector("#story-comment-content");
    const messageBox = document.querySelector("#comment-form-message");

    if (!storyId || !commentList) return;

    function showMessage(message, type = "error") {
        if (!messageBox) return;

        messageBox.textContent = message;
        messageBox.className = `comment-message ${type}`;
        messageBox.hidden = false;
    }

    function makeElement(tag, className, text) {
        const element = document.createElement(tag);

        if (className) element.className = className;
        if (text !== undefined) element.textContent = text;

        return element;
    }

    function formatDate(value) {
        if (!value) return "";

        const date = new Date(value);

        if (Number.isNaN(date.getTime())) return "";

        return date.toLocaleString(undefined, {
            dateStyle: "medium",
            timeStyle: "short"
        });
    }

    async function loadComments() {
        commentList.replaceChildren(
            makeElement("p", "comments-loading", "Loading comments...")
        );

        try {
            const response = await fetch(
                `/api/travel-stories/${encodeURIComponent(storyId)}/comments`
            );

            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.error || "Unable to load comments.");
            }

            renderComments(result.comments || []);

        } catch (error) {
            console.error("Comment loading failed:", error);

            commentList.replaceChildren(
                makeElement(
                    "p",
                    "comment-error",
                    "Unable to load comments. Please refresh the page."
                )
            );
        }
    }

    function renderComments(comments) {
        commentList.replaceChildren();

        const count = comments.length;

        if (commentCount) {
            commentCount.textContent =
                `${count} ${count === 1 ? "comment" : "comments"}`;
        }

        if (count === 0) {
            commentList.appendChild(
                makeElement(
                    "p",
                    "comments-empty",
                    "Be the first to share your thoughts about this journey."
                )
            );
            return;
        }

        const roots = comments.filter(comment => !comment.parent_id);
        const replies = comments.filter(comment => comment.parent_id);

        roots.forEach(comment => {
            const thread = makeElement("article", "comment-thread");

            thread.appendChild(renderComment(comment, false));

            const childReplies = replies.filter(
                reply => reply.parent_id === comment.id
            );

            if (childReplies.length > 0) {
                const replyList = makeElement("div", "comment-replies");

                childReplies.forEach(reply => {
                    replyList.appendChild(renderComment(reply, true));
                });

                thread.appendChild(replyList);
            }

            commentList.appendChild(thread);
        });
    }

    function renderComment(comment, isReply) {
        const card = makeElement(
            "article",
            isReply ? "comment-card comment-card-reply" : "comment-card"
        );

        const header = makeElement("div", "comment-header");
        const author = makeElement(
            "strong",
            "comment-author",
            comment.author || "GetOffDeals member"
        );
        const date = makeElement(
            "time",
            "comment-date",
            formatDate(comment.created_at)
        );

        header.append(author, date);

        const content = makeElement(
            "p",
            "comment-content",
            comment.content
        );

        const actions = makeElement("div", "comment-actions");

        if (authenticated && !isReply) {
            const replyButton = makeElement(
                "button",
                "comment-action-button",
                "Reply"
            );

            replyButton.type = "button";
            replyButton.addEventListener("click", () => {
                showReplyForm(card, comment.id);
            });

            actions.appendChild(replyButton);
        }

        if (authenticated && comment.can_delete) {
            const deleteButton = makeElement(
                "button",
                "comment-action-button comment-delete-button",
                "Delete"
            );

            deleteButton.type = "button";
            deleteButton.addEventListener("click", () => {
                deleteComment(comment.id);
            });

            actions.appendChild(deleteButton);
        }

        card.append(header, content, actions);

        return card;
    }

    function showReplyForm(parentCard, parentId) {
        if (!authenticated || parentCard.querySelector(".reply-form")) {
            return;
        }

        const form = makeElement("form", "reply-form");
        const textarea = makeElement("textarea", "reply-input");
        const actions = makeElement("div", "reply-form-actions");
        const cancelButton = makeElement(
            "button",
            "comment-action-button",
            "Cancel"
        );
        const submitButton = makeElement(
            "button",
            "stories-button reply-submit",
            "Post reply"
        );

        textarea.rows = 3;
        textarea.maxLength = 5000;
        textarea.placeholder = "Write your reply...";
        textarea.required = true;

        cancelButton.type = "button";
        submitButton.type = "submit";

        cancelButton.addEventListener("click", () => form.remove());

        actions.append(cancelButton, submitButton);
        form.append(textarea, actions);

        form.addEventListener("submit", async event => {
            event.preventDefault();

            const content = textarea.value.trim();

            if (!content || content.length > 5000) return;

            submitButton.disabled = true;
            submitButton.textContent = "Posting...";

            try {
                await submitComment(content, parentId);
                await loadComments();
            } catch (error) {
                showMessage(error.message);
                submitButton.disabled = false;
                submitButton.textContent = "Post reply";
            }
        });

        parentCard.appendChild(form);
        textarea.focus();
    }

    async function submitComment(content, parentId = null) {
        const response = await fetch(
            `/api/travel-stories/${encodeURIComponent(storyId)}/comments`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRF-Token": csrfToken
                },
                body: JSON.stringify({
                    content,
                    parent_id: parentId,
                    csrf_token: csrfToken
                })
            }
        );

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.error || "Unable to post your comment.");
        }

        return result;
    }

    async function deleteComment(commentId) {
        if (!window.confirm("Are you sure you want to delete this comment?")) {
            return;
        }

        try {
            const response = await fetch(
                `/api/story-comments/${encodeURIComponent(commentId)}`,
                {
                    method: "DELETE",
                    headers: {
                        "X-CSRF-Token": csrfToken
                    }
                }
            );

            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.error || "Unable to delete comment.");
            }

            await loadComments();

        } catch (error) {
            window.alert(error.message);
        }
    }

    if (commentForm) {
        commentForm.addEventListener("submit", async event => {
            event.preventDefault();

            const content = commentInput.value.trim();
            const submitButton = commentForm.querySelector(
                'button[type="submit"]'
            );

            if (!content || content.length > 5000) {
                showMessage("Your comment must contain 1–5,000 characters.");
                return;
            }

            if (!csrfToken) {
                showMessage("Your security token is missing. Refresh the page.");
                return;
            }

            submitButton.disabled = true;
            submitButton.textContent = "Posting...";

            try {
                await submitComment(content);
                commentInput.value = "";
                showMessage("Your comment has been posted.", "success");
                await loadComments();

            } catch (error) {
                showMessage(error.message);

            } finally {
                submitButton.disabled = false;
                submitButton.textContent = "Post comment";
            }
        });
    }

    loadComments();
}
