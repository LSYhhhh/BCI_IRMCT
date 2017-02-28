% processing in python:
clear; close all;clc;

dataPath = 'E:\data\ld3\fif';
dur = 4; % time period after L/R go
SP_filter = 'Laplacian';

left_go = 11;
right_go= 9;
files = dir([dataPath '\*.mat']);
dataAll = [];
for run = 1:length(files)
    file = files(run).name;
    disp(['[MI_dataset] Loading: ' file]);
    filename = [dataPath '\' file];
    load(filename)
    dataAll = cat(1,dataAll, signals');
end

%% L:
trigger.l_go = gettrigger(dataAll(:,1) == left_go);
for tr=1:length(trigger.l_go)    
    start = trigger.l_go(tr);
    dur = 4*fs-1;    
    trialsL(tr,:,:) = dataAll(start:start+dur,2:17);    
end
for tr=1:size(trialsL,1)
    
    disp(['Processing trial ' num2str(tr)]);
    psdL(tr,:,:,:) = processTrial(squeeze(trialsL(tr,:,:)), 'Laplacian');    
end
lpsdL = log(psdL);

% R
trigger.r_go = gettrigger(dataAll(:,1) == right_go);
for tr=1:length(trigger.r_go)    
    start = trigger.r_go(tr);
    dur = 4*fs-1;    
    trialsR(tr,:,:) = dataAll(start:start+dur,2:17);    
end
for tr=1:size(trialsR,1)
    
    disp(['Processing trial ' num2str(tr)]);
    psdR(tr,:,:,:) = processTrial(squeeze(trialsR(tr,:,:)), 'Laplacian');    
end
lpsdL = log(psdR);






