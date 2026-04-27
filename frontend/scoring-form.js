(function() {
  function escapeHtml(value) {
    if (window.CRMApp && CRMApp.escapeHtml) {
      return CRMApp.escapeHtml(value);
    }
    var div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
  }

  function calculateLevel(score) {
    if (score < 20) return 'E';
    if (score < 40) return 'D';
    if (score < 60) return 'C';
    if (score < 70) return 'B';
    return 'A';
  }

  function findFieldMeta(fields, fieldName) {
    return (fields || []).find(function(field) {
      return field.field === fieldName;
    }) || null;
  }

  function findOptionMeta(fieldMeta, value) {
    if (!fieldMeta || !fieldMeta.options) {
      return null;
    }
    return fieldMeta.options.find(function(option) {
      return option.value === value;
    }) || null;
  }

  function renderFields(container, fields) {
    if (!container) return;
    container.innerHTML = (fields || []).map(function(field) {
      return '' +
        '<div class="form-group">' +
          '<label for="score-' + escapeHtml(field.field) + '">' + escapeHtml(field.label) + '</label>' +
          '<select class="select scoring-select" id="score-' + escapeHtml(field.field) + '" data-score-field="' + escapeHtml(field.field) + '">' +
            '<option value="">请选择</option>' +
            field.options.map(function(option) {
              return '<option value="' + escapeHtml(option.value) + '">' +
                escapeHtml(option.label + '（' + option.score + '分）') +
              '</option>';
            }).join('') +
          '</select>' +
        '</div>';
    }).join('');
  }

  function getValues(container) {
    var values = {};
    Array.prototype.slice.call(container.querySelectorAll('[data-score-field]')).forEach(function(input) {
      values[input.getAttribute('data-score-field')] = input.value || null;
    });
    return values;
  }

  function setValues(container, fields, values) {
    (fields || []).forEach(function(field) {
      var input = container.querySelector('[data-score-field="' + field.field + '"]');
      if (input) {
        input.value = values && values[field.field] ? values[field.field] : '';
      }
    });
  }

  function setDisabled(container, disabled) {
    Array.prototype.slice.call(container.querySelectorAll('[data-score-field]')).forEach(function(input) {
      input.disabled = !!disabled;
      input.classList.toggle('readonly', !!disabled);
    });
  }

  function calculate(fields, values) {
    var total = 0;
    var details = (fields || []).map(function(field) {
      var selectedValue = values && values[field.field] ? values[field.field] : null;
      var option = findOptionMeta(field, selectedValue);
      var score = option ? Number(option.score || 0) : 0;
      total += score;
      return {
        field: field.field,
        label: field.label,
        value: selectedValue,
        valueLabel: option ? option.label : '',
        score: score
      };
    });

    return {
      totalScore: total,
      cardLevel: calculateLevel(total),
      details: details
    };
  }

  function renderPreview(summaryEl, detailEl, result) {
    if (summaryEl) {
      summaryEl.innerHTML = '' +
        '<div class="score-box">' +
          '<span class="score-box-label">当前总分</span>' +
          '<strong>' + escapeHtml(result.totalScore) + '</strong>' +
        '</div>' +
        '<div class="score-box">' +
          '<span class="score-box-label">当前卡级</span>' +
          '<strong>' + escapeHtml(result.cardLevel) + '</strong>' +
        '</div>';
    }

    if (detailEl) {
      detailEl.innerHTML = result.details.map(function(item) {
        return '' +
          '<div class="score-detail-item">' +
            '<span>' + escapeHtml(item.label) + '</span>' +
            '<span>' + escapeHtml(item.valueLabel || '-') + ' / ' + escapeHtml(item.score) + '分</span>' +
          '</div>';
      }).join('');
    }
  }

  window.CRMScoringForm = {
    calculate: calculate,
    findFieldMeta: findFieldMeta,
    findOptionMeta: findOptionMeta,
    getValues: getValues,
    renderFields: renderFields,
    renderPreview: renderPreview,
    setDisabled: setDisabled,
    setValues: setValues
  };
})();
