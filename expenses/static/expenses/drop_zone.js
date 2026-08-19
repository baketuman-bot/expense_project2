/* 汎用ファイルドロップゾーン。
   [data-drop-zone] を持つ要素をすべて初期化する。
   要素内の input[type=file] に multiple があれば複数選択に対応する。
   未選択時の表示文言は初期 innerHTML を保持して復元する。 */
(function () {
    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function init(zone) {
        var input = zone.querySelector('input[type="file"]');
        var promptEl = zone.querySelector('.drop-zone__prompt');
        if (!input || !promptEl) return;
        var listEl = zone.querySelector('.drop-zone__files');
        var defaultPrompt = promptEl.innerHTML;
        // 単一選択時のアイコン。既定は汎用の fa-file。中国輸出実績報告のように
        // 扱うファイル種別が固定の画面は data-file-icon で上書きする。
        var fileIcon = zone.dataset.fileIcon || 'fa-file';

        function render() {
            var files = input.files;
            if (!files || files.length === 0) {
                zone.classList.remove('selected');
                promptEl.innerHTML = defaultPrompt;
                if (listEl) listEl.innerHTML = '';
                return;
            }
            zone.classList.add('selected');
            if (input.multiple) {
                promptEl.innerHTML =
                    '<i class="fas fa-copy me-2"></i>' + files.length + '件のファイルを選択中';
            } else {
                promptEl.innerHTML =
                    '<i class="fas ' + fileIcon + ' me-2"></i>' + escapeHtml(files[0].name);
            }
            if (listEl) {
                listEl.innerHTML = '';
                for (var i = 0; i < files.length; i++) {
                    var li = document.createElement('li');
                    li.textContent = files[i].name;
                    listEl.appendChild(li);
                }
            }
        }

        function setFiles(fileList) {
            if (!fileList || !fileList.length || !window.DataTransfer) return;
            var dt = new DataTransfer();
            var limit = input.multiple ? fileList.length : 1;
            for (var i = 0; i < limit; i++) dt.items.add(fileList[i]);
            input.files = dt.files;
            render();
        }

        zone.addEventListener('click', function (e) {
            // input.click() の click イベントは zone まで bubble するため、
            // ここで弾かないと再帰的にファイル選択ダイアログを開こうとする
            if (e.target === input) return;
            input.click();
        });
        zone.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); }
        });
        zone.addEventListener('dragover', function (e) {
            e.preventDefault(); e.stopPropagation(); zone.classList.add('dragover');
        });
        zone.addEventListener('dragleave', function (e) {
            e.preventDefault(); e.stopPropagation(); zone.classList.remove('dragover');
        });
        zone.addEventListener('drop', function (e) {
            e.preventDefault(); e.stopPropagation(); zone.classList.remove('dragover');
            if (e.dataTransfer && e.dataTransfer.files) setFiles(e.dataTransfer.files);
        });
        input.addEventListener('change', render);
    }

    document.querySelectorAll('[data-drop-zone]').forEach(init);
})();
