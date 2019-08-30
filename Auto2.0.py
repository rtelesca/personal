'''
Created on Jun 12, 2019

@author: Ryan Telesca
'''
import csv
from pandas import DataFrame as pd
from pandas import read_csv as readCSV
from pandas import concat as concat
from pandas import to_datetime as toDateTime
from pandas import options as options
from datetime import date as dateLabel
from datetime import datetime as timeComp
from glob import glob as glob
from numpy import where as np
from numpy import count_nonzero as nonZ
from numpy import isnan as nancheck
from numpy import datetime64 as date64
from pyodbc import connect as connSQL
from os import path

options.mode.chained_assignment = None #turn off copy warnings for pandas

def merge(trovo, daily):
    
    '''need size from solve
    '''
    
    factorImport = open(glob(r'\\xsqnfs2.nyc.ime.reuters.com\TRPS\Bank Loans\Auto 2.0\Factor*.csv')[0], 'r')
    readFactors = csv.reader(factorImport)
    staleFactor = 10 #default
    for row in readFactors:
        if "Stale" in row[0] and row[1] not in (None, "", " "):
            staleFactor = float(row[1])
    
    factorImport.close()
    
    concatIndex = len(trovo.columns)
    trovo.insert(concatIndex, 'Concatenated', 1) #initializing stale column
    trovo.iloc[:, concatIndex] = trovo['lin'] + '_' + trovo['dealer'] #making unique lin for identification

    trovo = pd.merge(trovo, daily, how = 'left', on = 'Concatenated') #merging days unchanged/size/stale data
    unchangedIndex = trovo.columns.tolist().index('unchanged_for')
    daysStale = trovo.columns.tolist().index('days_stale')
    lastBidDate = trovo.columns.tolist().index('last_bid_date')
    
    trovo.iloc[:, daysStale] = trovo['days_stale'] + 1
    trovo.iloc[:, unchangedIndex] = trovo['unchanged_for'] + 1
    
    '''need size data still'''
    
    staleIndex = len(trovo.columns)
    trovo.insert(staleIndex, 'Not Stale', 1) #initializing stale column
    trovo.insert(staleIndex + 1, 'Color', 0) #initializing color column
    
    now = timeComp.now()     
    year = now.year
    month = now.month
    day = now.day
    
    trovo.iloc[:, lastBidDate] = toDateTime(trovo['last_bid_date'], errors = 'coerce')
    
    trovo.iloc[:, daysStale] = [0 if ~(x == date64('NaT')) and (x.year == year) and (x.month == month)  # updating quotes from today to be stale 0 days
              and (x.day == day) else y for (x, y) in list(zip(trovo['last_bid_date'], trovo['days_stale']))]
    
    trovo.iloc[:, staleIndex] = np((trovo['days_stale'] > staleFactor), 0, 1) #killing quotes stale for more than 10 days

    #outputting intermediate file after cleansing
    trovo.to_csv(r'\\xsqnfs2.nyc.ime.reuters.com\TRPS\Bank Loans\Auto 2.0\Place Results Here\FilterFile' + dateLabel.today().strftime('%m-%d-%Y') + '.csv', index = False)
        
    return trovo

def select(clean, hierarchy):
    
    #default values, will update if values present in excel file
    timeDecayF = 30 #volatile, drop this number - days unchanged > 30 gets killed
    stdDevTol = 1.28 #tolerance for number of std devs
    staleF = 10 #standard in Trovo
    
    factorImport = open(glob(r'\\xsqnfs2.nyc.ime.reuters.com\TRPS\Bank Loans\Auto 2.0\Factor*.csv')[0], 'r')
    readFactors = csv.reader(factorImport)
    for row in readFactors:
        if "Time" in row[0] and row[1] not in (None, "", " "):
            timeDecayF = float(row[1])
        if "Standard" in row[0] and row[1] not in (None, "", " "):
            stdDevTol = float(row[1])
        if "Stale" in row[0] and row[1] not in (None, "", " "):
            staleF = float(row[1])
    
    factorImport.close()
    
    hierarchyDict = {}
                
    for row in hierarchy.iterrows(): #inserting dealer rankings into dictionary
        hierarchyDict.update({row[1][0] : row[1][1]})
        
    finalFile = pd()
        
    clean.insert(len(clean.columns), 'DealerW', 0) #initializing dealer weight
    clean.insert(len(clean.columns), 'UnchangedW', 0) #initializing days unchanged weight
    clean.insert(len(clean.columns), 'StaleW', 0) #initializing stale weight
    
    clean.insert(len(clean.columns), 'Weight', 0) #initializing weights
    clean.insert(len(clean.columns), 'StdDev', 0) #initializing stdDev
    clean.insert(len(clean.columns), 'Calculated Bid', 0) #initializing avg bid
    clean.insert(len(clean.columns), 'Calculated Offer', 0) #initializing avg offer
    select = len(clean.columns)
    clean.insert(select, 'Select', 0) #initializing selection column
    staleIndex = clean.columns.tolist().index('Not Stale')
    clean.iloc[:, select] = clean.iloc[:, staleIndex] #copying over initial select values from stale values

    columns = clean.columns.tolist()
    stdDevIndex = columns.index('StdDev')
    weightIndex = columns.index('Weight')
    dealerIndex = columns.index('dealer')
    lastBidIndex = columns.index('last_bid')
    lastOfferIndex = columns.index('last_offer')
    colorIndex = columns.index('Color')
    unchangedIndex = columns.index('unchanged_for')
    calcBid = columns.index('Calculated Bid')
    calcOffer = columns.index('Calculated Offer')
    days_stale = columns.index('days_stale')
    dealerWIndex = columns.index('DealerW')
    unchangedWIndex = columns.index('UnchangedW')
    staleWIndex = columns.index('StaleW')
    bidDate = columns.index('last_bid_date')
        
    lins = clean.groupby('lin') #grouping quotes by their LINs
    
    hasColor = False #color is midpoint
    
    now = timeComp.now()     
    year = now.year
    month = now.month
    day = now.day
    
    for group, quotes in lins: #iterating through each LIN to do quote selection
        colorQuote = 0 #color quote price
        midpoint = 0 #midpoint price
        midpointW = 0 #midpoint weight
        stdDev = 0 #variable to get std dev
        hasColor = False
        numIncluded = 0 #number of quotes considered
        stdDevList = [] # keep track of bids to avoid double dataFrame loop
        tempFrame = pd()
        bestStaleBid = 0
        bestStaleAsk = 0
        bidPx = 0
        offerPx = 0
        stdDevDen = 0
        bestStaleW = 0
        
        if len(quotes) == 1: #if only quote, must use it
            for row in quotes.iterrows():
                data = row[1].to_frame().transpose() #skipping over index column
                data.iloc[0, select] = 1
                dealer = data.iloc[0, dealerIndex]
                lastBid = data.iloc[0, lastBidIndex]
                weight = 0
                dealerCheck = hierarchyDict.get(dealer) #dealer val
                staleVal = data.iloc[0, days_stale] #increment days stale (yesterday's data)
                daysStale = 0
                if nancheck(staleVal):
                    daysStale = 1
                else:
                    daysStale = staleVal
                if dealerCheck == None:
                    dealerW = 0.75
                else:
                    dealerW = 1 - (hierarchyDict.get(dealer) - 1)*.05 #dealer weighting
                unchVal = data.iloc[0, unchangedIndex] #increment days unchanged (yesterday's data)
                daysU = 0
                if nancheck(unchVal):
                    daysU = 1
                elif unchVal < daysStale: #error checking because Trovo isn't good
                    daysU = daysStale
                else:
                    daysU = unchVal #increment days unchanged (yesterday's data)
                updateW = 0
                if timeDecayF < 1:
                    date = data.iloc[0, bidDate]
                    if daysStale != 0:
                        updateW = 0.25
                    else:
                        diff = 0
                        diff += 60 * date.hour
                        diff += now.minute - date.minute
                        updateW = (timeDecayF * 400) / (diff + timeDecayF * 400) #400 is max in a trading day, will act nicely
                elif daysU >= 8 * timeDecayF: #days unchanged cutoff
                    updateW = 0.2
                else: #days unchanged weighting
                    updateW = (3 * timeDecayF) / (daysU + (3 * timeDecayF))
                '''need size weight'''
                staleW = (3 * staleF) /(daysStale + (3 * staleF)) #days stale weight
                weight =  dealerW * updateW * staleW
                data.iloc[0, dealerWIndex] = '{0:.5g}'.format(dealerW) #dealer weighting                    
                data.iloc[0, staleWIndex] = '{0:.5g}'.format(staleW) #stale weighting                    
                data.iloc[0, unchangedWIndex] = '{0:.5g}'.format(updateW) #unchanged weighting                    
                data.iloc[0, weightIndex] = '{0:.5g}'.format(weight) #final weighting
                tempFrame = concat([tempFrame, data.iloc[0, :].to_frame().transpose()])
                midpoint = data.iloc[0, lastBidIndex]
                bidPx = midpoint
                offerPx = data.iloc[0, lastOfferIndex]
        else:
            for row in quotes.iterrows(): #otherwise, iterate through all quotes and do selection process
                data = row[1].to_frame().transpose() #skipping over index column
                dealer = data.iloc[0, dealerIndex]
                lastBid = data.iloc[0, lastBidIndex]
                weight = 0
                if isinstance(dealer, float): #has color, mark it- dealer is NaN
                    data.iloc[0, lastOfferIndex] = data.iloc[0, lastBidIndex] #need to set offer price for calculations
                    if hasColor: #if two with color, make midpoint average of two
                        colorQuote = (colorQuote + lastBid) / 2
                    else:
                        hasColor= True
                        colorQuote = lastBid
                    weight = 1
                    data.iloc[0, colorIndex] = 1
                    data.iloc[0, dealerWIndex] = '{0:.5g}'.format(1) #dealer weighting                    
                    data.iloc[0, staleWIndex] = '{0:.5g}'.format(1) #stale weighting                    
                    data.iloc[0, unchangedWIndex] = '{0:.5g}'.format(1) #unchanged weighting                    
                    data.iloc[0, weightIndex] = '{0:.5g}'.format(weight) #final weighting 
                else:
                    dealerCheck = hierarchyDict.get(dealer) #dealer val
                    staleVal = data.iloc[0, days_stale] #increment days stale (yesterday's data)
                    daysStale = 0
                    if nancheck(staleVal):
                        daysStale = 1
                    else:
                        daysStale = staleVal
                    if dealerCheck == None:
                        dealerW = 0.75
                    else:
                        dealerW = 1 - (hierarchyDict.get(dealer) - 1)*.05 #dealer weighting
                    unchVal = data.iloc[0, unchangedIndex] #increment days unchanged (yesterday's data)
                    daysU = 0
                    if nancheck(unchVal):
                        daysU = 1
                        data.iloc[0, unchangedIndex] = 1
                    elif unchVal < daysStale: #error checking because Trovo isn't good
                        daysU = daysStale
                        data.iloc[0, unchangedIndex] = daysU
                    else:
                        daysU = unchVal #increment days unchanged (yesterday's data)
                    updateW = 0
                    if timeDecayF < 1:
                        try:
                            date, time, timeZone = data.iloc[0, bidDate].split(" ")
                            if int(date.split("-")[0]) != year or int(date.split("-")[1]) != month or int(date.split("-")[2]) != day:
                                updateW = 0.25
                            else:
                                diff = 0
                                time = time.split(":")
                                diff += 60 * (now.hour - int(time[0]))
                                diff += now.minute - int(time[1])
                                updateW = (timeDecayF * 400) / (diff + timeDecayF * 400) #400 is max in a trading day, will act nicely
                        except:
                            updateW = 0.25 #either no date of quote or it was before we kept track of time, very old
                    elif daysU >= 8 * timeDecayF: #days unchanged cutoff
                        updateW = 0.2
                    else: #days unchanged weighting
                        updateW = (3 * timeDecayF) / (daysU + (3 * timeDecayF))
                    '''need size weight'''
                    '''IF THERE IS SIZE< TIGHTEN STD DEV'''
                    staleW = (3 * staleF) /(daysStale + (3 * staleF)) #days stale weight
                    weight =  dealerW * updateW * staleW
                    data.iloc[0, dealerWIndex] = '{0:.5g}'.format(dealerW) #dealer weighting                    
                    data.iloc[0, staleWIndex] = '{0:.5g}'.format(staleW) #stale weighting                    
                    data.iloc[0, unchangedWIndex] = '{0:.5g}'.format(updateW) #unchanged weighting                    
                    data.iloc[0, weightIndex] = '{0:.5g}'.format(weight) #final weighting                    
                if data.iloc[0, select] == 1:
                    if weight > midpointW:
                        midpoint = lastBid
                        midpointW = weight
                    numIncluded += 1 #increment n
                    if weight > 0.6 or dealerW == 1:        
                        stdDevList.append(lastBid)
                        stdDevDen += 1
                if weight > bestStaleW:
                    bestStaleBid = lastBid
                    bestStaleAsk = data.iloc[0, lastOfferIndex]
                    bestStaleW = weight
                tempFrame = concat([tempFrame, data])
            if hasColor: #if color, auto midpoint
                midpoint = colorQuote
            if numIncluded == 0: #all stale
                if len(quotes) > 2:
                    numCalc = np(True, tempFrame['unchanged_for'], 0)
                    midpointUnch = min(numCalc)
                    midpointDraw = np(midpointUnch == tempFrame['unchanged_for'], tempFrame['last_bid'], 0)
                    midpoint = max(midpointDraw)
                    stdDev = 2
                    tempFrame.iloc[:, select] = np((abs(tempFrame['last_bid'] - midpoint) <= (stdDev*stdDevTol)), 1, 0)
                    numCalc = np((tempFrame['Select'] == 1), tempFrame['last_bid'], 0)
                    numInc = nonZ(numCalc)
                    bidPx = sum(numCalc)/numInc
                    offerPx = sum(np((tempFrame['Select'] == 1), tempFrame['last_offer'], 0))/numInc
                else:
                    tempFrame.iloc[:, select] = np((abs(tempFrame['last_bid'] - midpoint) <= (stdDev*stdDevTol)), 1, 0)
                    bidPx = bestStaleBid
                    offerPx = bestStaleAsk
                    midpoint = bestStaleBid
                    stdDev = 0
            else:
                '''IF THERE IS SIZE, TIGHTEN STD DEV, else do everything below'''
                if stdDevDen == 0:
                    stdDev = .25 #make very tight parameter but allow for depth
                else:
                    stdDev = ((sum([(x - midpoint)**2 for x in stdDevList])/(stdDevDen))**(1/2))
                    if stdDev < 0.25:
                        stdDev = 0.25
                    if stdDev > 5.0:
                        if midpoint < 80:
                            stdDev = 5.0
                        else:
                            stdDev = 3.0
                    elif stdDev > 3.0:
                        if midpoint >= 80:
                            stdDev = 3.0
                tempFrame.iloc[:, select] = np((abs(tempFrame['last_bid'] - midpoint) <= (stdDev*stdDevTol)) & tempFrame['Not Stale'] == 1, 1, 0)
                numCalc = np((tempFrame['Select'] == 1), tempFrame['last_bid'], 0)
                numInc = nonZ(numCalc)
                if numInc < 3 and stdDev == 0.25:
                    tempFrame.iloc[:, select] = np(((abs(tempFrame['last_bid'] - midpoint) <= (0.25*stdDevTol))), 1, 0) #too tight, add depth, stdDev 0.25
                    numCalc = np((tempFrame['Select'] == 1), tempFrame['last_bid'], 0)
                    numInc = nonZ(numCalc)
                bidPx = sum(numCalc)/numInc
                offerPx = sum(np((tempFrame['Select'] == 1), tempFrame['last_offer'], 0))/numInc
        tempFrame.iloc[:, stdDevIndex] = stdDev
        tempFrame.iloc[:, calcBid] = '%.3f' % bidPx
        tempFrame.iloc[:, calcOffer] = '%.3f' % offerPx
        finalFile = concat([finalFile, tempFrame])
    return finalFile

if __name__ == "__main__":
    print("Program Started")
    #downloading newest data from SQL Server
    SQLConnection = connSQL('DRIVER={SQL SERVER};server=10.91.141.195;database=Pricing_BankLoans;uid=pricing_user_BankLoans;pwd=bankloans')
    SQLNavigator = SQLConnection.cursor()
    SQLNavigator.execute('''select CONCAT(lin,'_', dealer) as Concatenated, unchanged_for, days_stale from [Pricing_BankLoans].[Main].[DailyInputTable]
                             where trovo_asof = (select max(trovo_asof) from [Pricing_BankLoans].[Main].[DailyInputTable]) 
                             and snap_name = '4pm_finalized_snap' 
                             and region = 'US' ''') #(select max(trovo_asof) from [Pricing_BankLoans].[Main].[DailyInputTable])
    
    print("SQL Done")
    
    newDaily = open(glob(r'\\xsqnfs2.nyc.ime.reuters.com\TRPS\Bank Loans\Auto 2.0\Algo\Input\D*.csv')[0], 'w', newline='')
    writeDaily = csv.writer(newDaily)
    
    header = ['Concatenated', 'unchanged_for', 'days_stale'] #defining header for daily file
    writeDaily.writerow(header)
    
    for row in SQLNavigator:
        writeDaily.writerow(row)
        
    newDaily.close()
    
    hierarchyFile = readCSV(glob(r'\\xsqnfs2.nyc.ime.reuters.com\TRPS\Bank Loans\Auto 2.0\Algo\Input\B*.csv')[0]) #dealer hierarchy
    
    trovoFiles = glob(r'\\xsqnfs2.nyc.ime.reuters.com\TRPS\Bank Loans\Auto 2.0\Trovo\mw-set*.csv')
    trovoFiles.sort(key=path.getmtime, reverse = True)
        
    trovoFile = readCSV(trovoFiles[0]) #most recent trovo file  
    dailyFile = readCSV(glob(r'\\xsqnfs2.nyc.ime.reuters.com\TRPS\Bank Loans\Auto 2.0\Algo\Input\D*.csv')[0]) #yesterday's dailyInputFile
    
    print("merge started")
    
    cleanFile = merge(trovoFile, dailyFile) #file after merging data and killing stale quotes
    
    print("select started")
    
    cleanFile = select(cleanFile, hierarchyFile) #file after selections are made
    
    #exporting final file
    cleanFile.to_csv(r'\\xsqnfs2.nyc.ime.reuters.com\TRPS\Bank Loans\Auto 2.0\OutputFile' + dateLabel.today().strftime('%m-%d-%Y') + '.csv', index = False)

    print(' ')
    print(' ')
    print('Done! Close this window and upload OutputFile to Trovo.')
