%% ORGANIZE_RECEIVED_DATA Organize a converted capture by CS procedure.
%
% The Python application exports captures to MAT files with the following
% result tables:
%   results.subevents  - one row per received CS subevent
%   results.steps      - steps referenced by each subevent
%   results.tones      - tones referenced by each step
%
% This script creates one element of organizedData per procedure.  Each
% element contains the matching subevents, steps, and tones, together with
% the original (one-based MATLAB) row indices.  Both local HCI and RAS
% subevents are retained when they belong to the same procedure.
%
% Set inputFile and outputFile below for non-interactive use.  If inputFile
% is empty, a file picker is opened.  The output is saved next to the input
% unless outputFile is supplied.

inputFile = "";   % Example: "../python/recordings/session_name.mat"
outputFile = "";  % Empty -> <input name>_organized.mat

if strlength(string(inputFile)) == 0
    [name, folder] = uigetfile("*.mat", "Select a converted CS capture");
    if isequal(name, 0)
        error("organize_received_data:NoInput", "No MAT file was selected.");
    end
    inputFile = fullfile(folder, name);
end

inputFile = char(inputFile);
if ~isfile(inputFile)
    error("organize_received_data:MissingInput", "Input file does not exist: %s", inputFile);
end

capture = load(inputFile, "results");
if ~isfield(capture, "results")
    error("organize_received_data:MissingResults", ...
        "The MAT file does not contain a results variable.");
end

organizedData = organizeByProcedure(capture.results);
if isempty(organizedData)
    procedureIds = zeros(0, 0);
else
    procedureIds = vertcat(organizedData.procedureKey);
end
sourceFile = inputFile;

if strlength(string(outputFile)) == 0
    [folder, stem, ~] = fileparts(inputFile);
    outputFile = fullfile(folder, [stem '_organized.mat']);
end
outputFile = char(outputFile);

if isfile(outputFile)
    error("organize_received_data:OutputExists", ...
        "Output already exists; choose another outputFile: %s", outputFile);
end

% -v7.3 keeps the script usable for long captures and large tone tables.
save(outputFile, "organizedData", "procedureIds", "sourceFile", "-v7.3");
fprintf("Organized %d procedures from %s\n", numel(organizedData), inputFile);
fprintf("Saved organized data to %s\n", outputFile);


function organizedData = organizeByProcedure(results)
%ORGANIZEBYPROCEDURE Build a procedure-indexed struct array.

if ~isfield(results, "subevents") || ~isfield(results.subevents, "procedure_counter")
    error("organize_received_data:MissingSubevents", ...
        "results.subevents.procedure_counter is required.");
end

subevents = results.subevents;
subeventCount = numel(subevents.procedure_counter);
if subeventCount == 0
    organizedData = repmat(emptyProcedureStruct(), 0, 1);
    return;
end

% A procedure is identified by the same tuple used by the capture history:
% configuration ID, ACL event at the start, and the controller counter.
% Falling back to the counter keeps the script compatible with older MAT
% exports that did not contain all three fields.
keyNames = {'config_id', 'start_acl_conn_event', 'procedure_counter'};
keyWidth = sum(isfield(subevents, keyNames));
keys = zeros(subeventCount, max(1, keyWidth));
keyColumn = 0;
for column = 1:numel(keyNames)
    if isfield(subevents, keyNames{column})
        keyColumn = keyColumn + 1;
        keys(:, keyColumn) = columnVector(subevents.(keyNames{column}), subeventCount);
    end
end

if keyWidth == 0
    error("organize_received_data:MissingProcedureKey", ...
        "No procedure-identifying field was found in results.subevents.");
end

[uniqueKeys, ~, groupNumber] = unique(keys, "rows");
procedureCount = size(uniqueKeys, 1);
organizedData = repmat(emptyProcedureStruct(), procedureCount, 1);

for procedureNumber = 1:procedureCount
    subeventIndices = find(groupNumber == procedureNumber);
    stepIndices = findStepsForSubevents(results, subeventIndices);
    toneIndices = findTonesForSteps(results, stepIndices);

    key = uniqueKeys(procedureNumber, :);
    procedure = emptyProcedureStruct();
    procedure.procedureKey = key;
    procedure.procedureCounter = key(end);
    procedure.subeventIndices = subeventIndices;
    procedure.stepIndices = stepIndices;
    procedure.toneIndices = toneIndices;
    procedure.subevents = selectRows(subevents, subeventIndices, subeventCount);

    if isfield(results, "steps")
        procedure.steps = selectRows(results.steps, stepIndices, fieldLength(results.steps));
    end
    if isfield(results, "tones")
        procedure.tones = selectRows(results.tones, toneIndices, fieldLength(results.tones));
    end

    procedure.summary = summarizeProcedure(procedure.subevents, procedure.steps, procedure.tones, key);
    organizedData(procedureNumber) = procedure;
end
end


function indices = findStepsForSubevents(results, subeventIndices)
% Return one-based rows of results.steps for the selected subevents.

if ~isfield(results, "steps") || ~isfield(results.steps, "subevent_row")
    indices = zeros(0, 1);
    return;
end

steps = results.steps;
stepSubeventRows = columnVector(steps.subevent_row, fieldLength(steps));
% HDF5 row references are zero-based; MATLAB indices are one-based.
indices = find(ismember(stepSubeventRows, subeventIndices - 1));
end


function indices = findTonesForSteps(results, stepIndices)
% Return one-based rows of results.tones for the selected steps.

if ~isfield(results, "tones") || ~isfield(results.tones, "step_row")
    indices = zeros(0, 1);
    return;
end

tones = results.tones;
toneStepRows = columnVector(tones.step_row, fieldLength(tones));
% As above, step_row refers to a zero-based HDF5 step row.
indices = find(ismember(toneStepRows, stepIndices - 1));
end


function summary = summarizeProcedure(subevents, steps, tones, key)
% Add compact counts and timing information without discarding raw fields.

summary = struct();
summary.procedureKey = key;
summary.procedureCounter = key(end);
summary.numSubevents = fieldLength(subevents);
summary.numSteps = fieldLength(steps);
summary.numTones = fieldLength(tones);

if isfield(subevents, "t_host") && ~isempty(subevents.t_host)
    timestamps = double(subevents.t_host(:));
    timestamps = timestamps(isfinite(timestamps));
    if ~isempty(timestamps)
        summary.firstTimestamp = min(timestamps);
        summary.lastTimestamp = max(timestamps);
    else
        summary.firstTimestamp = NaN;
        summary.lastTimestamp = NaN;
    end
else
    summary.firstTimestamp = NaN;
    summary.lastTimestamp = NaN;
end

if isfield(subevents, "role")
    summary.roles = unique(double(subevents.role(:))).';
else
    summary.roles = zeros(1, 0);
end
end


function selected = selectRows(source, indices, sourceCount)
% Select rows from each field while preserving the source table structure.

selected = struct();
if isempty(source) || ~isstruct(source)
    return;
end

names = fieldnames(source);
for fieldNumber = 1:numel(names)
    name = names{fieldNumber};
    selected.(name) = selectValue(source.(name), indices, sourceCount);
end
end


function selected = selectValue(value, indices, sourceCount)
% Select a table-aligned value, including cell arrays of MATLAB char rows.

if isempty(value) || sourceCount == 0
    selected = value;
elseif iscell(value) || isstring(value)
    if numel(value) == sourceCount
        selected = value(:);
        selected = selected(indices);
    else
        selected = value;
    end
elseif ischar(value)
    if size(value, 1) == sourceCount
        selected = value(indices, :);
    else
        selected = value;
    end
elseif isnumeric(value) || islogical(value)
    if isvector(value) && numel(value) == sourceCount
        selected = value(:);
        selected = selected(indices);
    elseif size(value, 1) == sourceCount
        selected = value(indices, :);
    else
        selected = value;
    end
else
    % Metadata or an unfamiliar non-tabular value is kept unchanged.
    selected = value;
end
end


function result = columnVector(value, expectedCount)
% Convert a table column to double for grouping and comparisons.

if numel(value) ~= expectedCount
    error("organize_received_data:InvalidColumn", ...
        "A results column has %d values; expected %d.", numel(value), expectedCount);
end
result = double(value(:));
end


function count = fieldLength(tableData)
% Infer the number of rows from a converted MAT table struct.

if isempty(tableData) || ~isstruct(tableData)
    count = 0;
    return;
end

names = fieldnames(tableData);
if isempty(names)
    count = 0;
    return;
end

value = tableData.(names{1});
count = numel(value);
if ischar(value) && size(value, 1) > 1
    count = size(value, 1);
end
end


function empty = emptyProcedureStruct()
% Keep the output schema stable even when a capture has no subevents.

empty = struct( ...
    "procedureKey", zeros(1, 0), ...
    "procedureCounter", [], ...
    "subeventIndices", zeros(0, 1), ...
    "stepIndices", zeros(0, 1), ...
    "toneIndices", zeros(0, 1), ...
    "subevents", struct(), ...
    "steps", struct(), ...
    "tones", struct(), ...
    "summary", struct());
end
